#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СберЗвук Мультибот - Мощный универсальный инструмент для работы с API СберЗвука
Версия: 2.0
Автор: AI Assistant
Дата: 12 сентября 2025
"""

import asyncio
import aiohttp
import json
import os
import sys
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from urllib.parse import urljoin
import random
from datetime import datetime

# Импортируем наши модули
from audio_metadata import AudioMetadataManager, QualityChecker, get_file_extension_for_quality, estimate_file_size

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('zvuk_multibot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ZvukConfig:
    """Конфигурация для работы с API СберЗвука"""
    base_url: str = "https://zvuk.com"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    auth_token: str = ""
    timeout: int = 60
    max_retries: int = 5
    retry_delay: int = 3
    concurrent_requests: int = 2
    download_path: str = "./downloads"
    
    def __post_init__(self):
        os.makedirs(self.download_path, exist_ok=True)

class ZvukMultiBot:
    """Мощный мультибот для работы с API СберЗвука"""
    
    def __init__(self, config: ZvukConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.semaphore = asyncio.Semaphore(config.concurrent_requests)
        self.metadata_manager: Optional[AudioMetadataManager] = None
        self.quality_checker: Optional[QualityChecker] = None
        self.stats = {
            'requests_made': 0,
            'successful_downloads': 0,
            'failed_downloads': 0,
            'total_data_downloaded': 0,
            'metadata_embedded': 0,
            'covers_downloaded': 0
        }
        
    async def __aenter__(self):
        """Асинхронный контекстный менеджер"""
        await self.start_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии"""
        await self.close_session()
    
    async def start_session(self):
        """Инициализация HTTP сессии"""
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=2,
            ttl_dns_cache=300,
            use_dns_cache=True,
            ssl=False
        )
        
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        
        headers = {
            'User-Agent': self.config.user_agent,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'DNT': '1'
        }
        
        # Используем cookie вместо заголовка для токена
        cookies = {'auth': self.config.auth_token}
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers,
            cookies=cookies
        )
        
        # Инициализируем менеджеры
        self.metadata_manager = AudioMetadataManager(self.session)
        self.quality_checker = QualityChecker(self.session, self.config.base_url)
        
        logger.info("HTTP сессия инициализирована")
    
    async def close_session(self):
        """Закрытие HTTP сессии"""
        if self.session:
            await self.session.close()
            logger.info("HTTP сессия закрыта")
    
    async def make_request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Универсальный метод для выполнения HTTP запросов"""
        async with self.semaphore:
            url = urljoin(self.config.base_url, endpoint)
            
            # Добавляем случайную задержку для имитации человеческого поведения
            delay = random.uniform(1.0, 3.0)
            await asyncio.sleep(delay)
            
            for attempt in range(self.config.max_retries):
                try:
                    self.stats['requests_made'] += 1
                    
                    async with self.session.request(method, url, **kwargs) as response:
                        if response.status == 418:  # I'm a teapot - антибот защита
                            wait_time = self.config.retry_delay * (attempt + 1) * 2
                            logger.warning(f"Получен код 418, ждем {wait_time} секунд...")
                            await asyncio.sleep(wait_time)
                            continue
                        
                        if response.status == 200:
                            content_type = response.headers.get('content-type', '')
                            
                            if 'application/json' in content_type:
                                data = await response.json()
                                return data
                            else:
                                # Возвращаем бинарные данные для аудиофайлов
                                data = await response.read()
                                return {'binary_data': data, 'content_type': content_type}
                        
                        logger.error(f"HTTP {response.status}: {await response.text()}")
                        
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут запроса к {url} (попытка {attempt + 1})")
                except Exception as e:
                    logger.error(f"Ошибка запроса к {url}: {e}")
                
                if attempt < self.config.max_retries - 1:
                    wait_time = self.config.retry_delay * (attempt + 1)
                    await asyncio.sleep(wait_time)
            
            return None
    
    async def get_profile(self) -> Optional[Dict]:
        """Получение информации о профиле пользователя"""
        logger.info("Получение информации о профиле...")
        return await self.make_request('GET', '/api/v2/tiny/profile')
    
    async def get_tracks(self, track_ids: List[int], include_details: bool = True) -> Optional[Dict]:
        """Получение информации о треках"""
        ids_str = ','.join(map(str, track_ids))
        params = {'ids': ids_str}
        
        if include_details:
            params['include'] = 'track'
        
        logger.info(f"Получение информации о треках: {track_ids}")
        return await self.make_request('GET', '/api/tiny/tracks', params=params)
    
    async def get_releases(self, release_ids: List[int], include_tracks: bool = True) -> Optional[Dict]:
        """Получение информации о релизах"""
        ids_str = ','.join(map(str, release_ids))
        params = {'ids': ids_str}
        
        if include_tracks:
            params['include'] = 'track'
        
        logger.info(f"Получение информации о релизах: {release_ids}")
        return await self.make_request('GET', '/api/tiny/releases', params=params)
    
    async def get_playlists(self, playlist_ids: List[int], include_tracks: bool = True) -> Optional[Dict]:
        """Получение информации о плейлистах"""
        ids_str = ','.join(map(str, playlist_ids))
        params = {'ids': ids_str}
        
        if include_tracks:
            params['include'] = 'track'
        
        logger.info(f"Получение информации о плейлистах: {playlist_ids}")
        return await self.make_request('GET', '/api/tiny/playlists', params=params)
    
    async def get_stream_url(self, track_id: int, quality: str = 'high') -> Optional[str]:
        """Получение ссылки на аудиопоток"""
        params = {'id': track_id, 'quality': quality}
        
        logger.info(f"Получение ссылки на трек {track_id} (качество: {quality})")
        response = await self.make_request('GET', '/api/tiny/track/stream', params=params)
        
        if response and 'result' in response and 'stream' in response['result']:
            return response['result']['stream']
        
        return None
    
    async def get_lyrics(self, track_id: int) -> Optional[str]:
        """Получение текста песни"""
        params = {'track_id': track_id}
        
        logger.info(f"Получение текста для трека {track_id}")
        response = await self.make_request('GET', '/api/tiny/lyrics', params=params)
        
        if response and 'result' in response and 'lyrics' in response['result']:
            return response['result']['lyrics']
        
        return None
    
    async def graphql_query(self, query: str, variables: Dict = None) -> Optional[Dict]:
        """Выполнение GraphQL запроса"""
        payload = {
            'query': query,
            'variables': variables or {}
        }
        
        headers = {'Content-Type': 'application/json'}
        
        logger.info("Выполнение GraphQL запроса")
        return await self.make_request('POST', '/api/v1/graphql', 
                                     json=payload, headers=headers)
    
    async def get_artist_releases(self, artist_id: int, limit: int = 50, offset: int = 0) -> List[int]:
        """Получение релизов артиста через GraphQL с пагинацией.

        Возвращает до ``limit`` идентификаторов релизов. Если ``limit`` <= 0,
        вернёт все доступные релизы (до исчерпания выдачи API).
        """
        collected: List[int] = []
        page_size = 50 if limit is None or limit <= 0 else min(50, limit)

        query = """
        query getArtistReleases($id: ID!, $limit: Int!, $offset: Int!) {
            getArtists(ids: [$id]) {
                releases(limit: $limit, offset: $offset) {
                    id
                }
            }
        }
        """

        current_offset = offset
        while True:
            variables = {
                'id': str(artist_id),
                'limit': page_size,
                'offset': current_offset
            }

            response = await self.graphql_query(query, variables)

            if not (response and 'data' in response and 'getArtists' in response['data'] and response['data']['getArtists']):
                break

            releases = response['data']['getArtists'][0].get('releases', [])
            if not releases:
                break

            collected.extend(int(r['id']) for r in releases if 'id' in r)

            # Если задан лимит и мы его набрали — останавливаемся
            if limit > 0 and len(collected) >= limit:
                collected = collected[:limit]
                break

            # Иначе продолжаем пагинацию
            current_offset += len(releases)

            # Небольшая пауза, чтобы не долбить API
            await asyncio.sleep(0.3)

        return collected
    
    async def check_track_qualities(self, track_id: int) -> Dict[str, Dict]:
        """Проверка всех доступных качеств для трека"""
        return await self.quality_checker.check_all_qualities(track_id)
    
    async def get_track_with_quality_info(self, track_id: int) -> Optional[Dict]:
        """Получение информации о треке с проверкой качеств"""
        # Получаем основную информацию
        track_info = await self.get_tracks([track_id])
        if not track_info or 'result' not in track_info:
            return None
        
        track_data = track_info['result']['tracks'].get(str(track_id))
        if not track_data:
            return None
        
        # Добавляем информацию о качествах
        quality_results = await self.check_track_qualities(track_id)
        track_data['quality_check'] = quality_results
        
        # Добавляем рекомендуемое качество
        best_quality = self.quality_checker.get_best_available_quality(quality_results)
        track_data['recommended_quality'] = best_quality
        
        # Добавляем оценки размеров файлов
        duration = track_data.get('duration', 0)
        track_data['estimated_sizes'] = {}
        for quality in ['flac', 'high', 'mid']:
            if quality_results.get(quality, {}).get('available', False):
                track_data['estimated_sizes'][quality] = estimate_file_size(duration, quality)
        
        return track_data
    
    async def download_track(self, track_id: int, quality: str = 'high', 
                           custom_filename: str = None, embed_metadata: bool = True,
                           download_cover: bool = True, target_dir: Optional[Path] = None,
                           position: Optional[int] = None, save_lyrics: bool = False, save_subtitles: bool = False) -> bool:
        """Скачивание трека с метаданными и обложкой"""
        try:
            # Получаем информацию о треке
            track_info = await self.get_tracks([track_id])
            if not track_info or 'result' not in track_info:
                logger.error(f"Не удалось получить информацию о треке {track_id}")
                return False
            
            track_data = track_info['result']['tracks'].get(str(track_id))
            if not track_data:
                logger.error(f"Трек {track_id} не найден")
                return False
            
            # Проверяем доступность качества
            if embed_metadata:
                quality_results = await self.check_track_qualities(track_id)
                if not quality_results.get(quality, {}).get('available', False):
                    logger.warning(f"Качество {quality} недоступно для трека {track_id}")
                    # Пытаемся найти лучшее доступное качество
                    best_quality = self.quality_checker.get_best_available_quality(quality_results)
                    if best_quality:
                        logger.info(f"Используем качество {best_quality} вместо {quality}")
                        quality = best_quality
                    else:
                        logger.error(f"Нет доступных качеств для трека {track_id}")
                        return False
            
            # Получаем ссылку на поток
            stream_url = await self.get_stream_url(track_id, quality)
            if not stream_url:
                logger.error(f"Не удалось получить ссылку на трек {track_id}")
                return False
            
            # Формируем целевой каталог
            dest_dir = Path(target_dir) if target_dir else Path(self.config.download_path)
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Формируем имя файла
            if custom_filename:
                filename = custom_filename
            else:
                artist = track_data.get('artist_names', ['Unknown'])[0]
                title = track_data.get('title', 'Unknown')
                extension = get_file_extension_for_quality(quality)[1:]  # убираем точку
                base_name = f"{artist} - {title}.{extension}"
                # Очищаем имя файла от недопустимых символов
                base_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
                if isinstance(position, int) and position > 0:
                    filename = f"{position:02d}. {base_name}"
                else:
                    filename = base_name

            filepath = dest_dir / filename
            
            # Скачиваем файл
            logger.info(f"Скачивание трека: {filepath}")
            
            async with self.session.get(stream_url) as response:
                if response.status == 200:
                    with open(filepath, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            self.stats['total_data_downloaded'] += len(chunk)
                    
                    file_size = filepath.stat().st_size
                    logger.info(f"Трек успешно скачан: {filepath} ({file_size} байт)")
                    self.stats['successful_downloads'] += 1
                    
                    # Внедряем метаданные если нужно
                    if embed_metadata:
                        await self._embed_track_metadata(filepath, track_data, track_id, download_cover, save_lyrics, save_subtitles)
                    else:
                        # Если метаданные не встраиваем, но нужно сохранить текст/субтитры рядом
                        if save_lyrics or save_subtitles:
                            try:
                                lyrics_raw = await self.get_lyrics(track_id)
                                if lyrics_raw:
                                    plain_text, lrc_text = self.metadata_manager.split_lyrics_formats(lyrics_raw)
                                    if save_lyrics:
                                        if lrc_text:
                                            (filepath.with_suffix('.lrc')).write_text(lrc_text, encoding='utf-8')
                                            logger.info(f"Сохранён LRC: {filepath.with_suffix('.lrc')}")
                                        elif plain_text:
                                            (filepath.with_suffix('.txt')).write_text(plain_text, encoding='utf-8')
                                            logger.info(f"Сохранён текст: {filepath.with_suffix('.txt')}")
                                    if save_subtitles and lrc_text:
                                        srt_text = self.metadata_manager.lrc_to_srt(lrc_text)
                                        if srt_text:
                                            (filepath.with_suffix('.srt')).write_text(srt_text, encoding='utf-8')
                                            logger.info(f"Сохранён SRT: {filepath.with_suffix('.srt')}")
                            except Exception as e:
                                logger.warning(f"Не удалось сохранить текст/субтитры рядом с файлом: {e}")
                    
                    return True
                else:
                    logger.error(f"Ошибка скачивания: HTTP {response.status}")
            
        except Exception as e:
            logger.error(f"Ошибка при скачивании трека {track_id}: {e}")
        
        self.stats['failed_downloads'] += 1
        return False
    
    async def _embed_track_metadata(self, filepath: Path, track_data: Dict, track_id: int, download_cover: bool = True, save_lyrics: bool = False, save_subtitles: bool = False):
        """Внедрение метаданных в трек"""
        try:
            # Получаем текст песни
            lyrics = None
            lrc_text = None
            try:
                lyrics = await self.get_lyrics(track_id)
                if lyrics:
                    logger.info("Получен текст песни")
                    # Определяем формат текста: LRC или обычный
                    plain_text, lrc_text = self.metadata_manager.split_lyrics_formats(lyrics)
                    if plain_text:
                        lyrics = plain_text
            except Exception as e:
                logger.warning(f"Не удалось получить текст песни: {e}")
            
            # Скачиваем обложку
            cover_data = None
            if download_cover and track_data.get('image', {}).get('src'):
                try:
                    cover_url = track_data['image']['src']
                    cover_data = await self.metadata_manager.download_cover_art(cover_url, size="1000x1000")
                    if cover_data:
                        # Оптимизируем обложку
                        cover_data = self.metadata_manager.optimize_cover_image(cover_data)
                        self.stats['covers_downloaded'] += 1
                        logger.info("Обложка успешно скачана и оптимизирована")
                except Exception as e:
                    logger.warning(f"Не удалось скачать обложку: {e}")
            
            # Внедряем метаданные: если есть LRC — кладём LRC (FLAC) или SYLT (MP3); иначе обычный текст
            if self.metadata_manager.embed_metadata(filepath, track_data, lyrics, cover_data, lrc_text):
                self.stats['metadata_embedded'] += 1
                logger.info("Метаданные успешно внедрены")
            else:
                logger.warning("Не удалось внедрить метаданные")

            # Сохраняем текст рядом, если нужно
            if (save_lyrics or save_subtitles) and (lyrics or lrc_text):
                try:
                    lyrics_dir = filepath.parent
                    base_name = filepath.stem
                    if save_lyrics:
                        if lrc_text:
                            out_lrc = lyrics_dir / f"{base_name}.lrc"
                            out_lrc.write_text(lrc_text, encoding='utf-8')
                            logger.info(f"Сохранён LRC: {out_lrc}")
                        else:
                            out_txt = lyrics_dir / f"{base_name}.txt"
                            out_txt.write_text(lyrics or "", encoding='utf-8')
                            logger.info(f"Сохранён текст: {out_txt}")
                    if save_subtitles and lrc_text:
                        srt_text = self.metadata_manager.lrc_to_srt(lrc_text)
                        if srt_text:
                            out_srt = lyrics_dir / f"{base_name}.srt"
                            out_srt.write_text(srt_text, encoding='utf-8')
                            logger.info(f"Сохранён SRT: {out_srt}")
                except Exception as e:
                    logger.warning(f"Не удалось сохранить текст рядом с файлом: {e}")
                
        except Exception as e:
            logger.error(f"Ошибка при внедрении метаданных: {e}")
    
    async def download_release(self, release_id: int, quality: str = 'high', save_lyrics: bool = False, save_subtitles: bool = False, album_index: Optional[int] = None) -> int:
        """Скачивание всего релиза"""
        logger.info(f"Начинаем скачивание релиза {release_id}")
        
        # Получаем информацию о релизе
        release_info = await self.get_releases([release_id], include_tracks=True)
        if not release_info or 'result' not in release_info:
            logger.error(f"Не удалось получить информацию о релизе {release_id}")
            return 0
        
        release_data = release_info['result']['releases'].get(str(release_id))
        tracks_data = release_info['result'].get('tracks', {})
        
        if not release_data or not tracks_data:
            logger.error(f"Релиз {release_id} не найден или пуст")
            return 0
        
        # Создаем папку для релиза с красивым именем: NN. [YEAR] Title [LP]
        release_title = release_data.get('title', f'Release_{release_id}')
        # Год
        year_str = None
        date_val = release_data.get('date')
        if date_val:
            ds = str(date_val)
            if len(ds) >= 4 and ds[:4].isdigit():
                year_str = ds[:4]
        # Метка LP/EP/SINGLE
        release_type = release_data.get('type', '')
        track_ids = release_data.get('track_ids', [])
        label = None
        if release_type == 'album':
            label = 'LP'
        elif isinstance(track_ids, list):
            if len(track_ids) == 1:
                label = 'SINGLE'
            elif 2 <= len(track_ids) <= 6:
                label = 'EP'
        # Составляем имя
        name_parts: List[str] = []
        if isinstance(album_index, int) and album_index > 0:
            name_parts.append(f"{album_index:02d}.")
        if year_str:
            name_parts.append(f"[{year_str}]")
        name_parts.append(release_title)
        if label:
            name_parts.append(f"[{label}]")
        folder_name = " ".join(name_parts)
        # Санитизация имени папки
        folder_name = "".join(c for c in folder_name if c.isalnum() or c in (' ', '-', '_', '.', '[', ']')).rstrip()
        release_folder = Path(self.config.download_path) / folder_name
        release_folder.mkdir(exist_ok=True)
        
        # Скачиваем все треки
        downloaded_count = 0
        
        tasks = []
        for track_id in track_ids:
            track_info = tracks_data.get(str(track_id), {})
            if track_info:
                position = track_info.get('position', 0)
                # Используем общий метод скачивания, чтобы учитывать статистику и метаданные
                tasks.append(self.download_track(
                    track_id=track_id,
                    quality=quality,
                    custom_filename=None,
                    embed_metadata=True,
                    download_cover=True,
                    target_dir=release_folder,
                    position=position,
                    save_lyrics=save_lyrics,
                    save_subtitles=save_subtitles
                ))

        # Выполняем скачивание параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)
        downloaded_count = sum(1 for result in results if result is True)
        
        logger.info(f"Релиз {release_id} скачан: {downloaded_count}/{len(track_ids)} треков")
        return downloaded_count
    
    # Удален дублирующий метод download_track_to_path: функциональность объединена в download_track
    
    # Убран незавершенный метод search_content для упрощения кода
    
    def print_stats(self):
        """Вывод статистики"""
        print("\n" + "="*50)
        print("СТАТИСТИКА РАБОТЫ БОТА")
        print("="*50)
        print(f"Запросов выполнено: {self.stats['requests_made']}")
        print(f"Успешных скачиваний: {self.stats['successful_downloads']}")
        print(f"Неудачных скачиваний: {self.stats['failed_downloads']}")
        print(f"Данных скачано: {self.stats['total_data_downloaded'] / (1024*1024):.2f} МБ")
        print(f"Метаданных внедрено: {self.stats['metadata_embedded']}")
        print(f"Обложек скачано: {self.stats['covers_downloaded']}")
        print("="*50)

class ZvukMultiBotCLI:
    """Командный интерфейс для мультибота"""
    
    def __init__(self):
        self.parser = self.create_parser()
    
    def create_parser(self):
        """Создание парсера аргументов командной строки"""
        parser = argparse.ArgumentParser(
            description='СберЗвук Мультибот - Мощный инструмент для работы с API',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Примеры использования с короткими командами:

  # Информация о профиле
  python zvuk_multibot.py prof
  python zvuk_multibot.py p

  # Скачивание треков  
  python zvuk_multibot.py dl 116136641 -q flac      # FLAC качество
  python zvuk_multibot.py download 116136641 -q high -f "track.mp3"
  
  # Проверка качества
  python zvuk_multibot.py chk 116136641
  python zvuk_multibot.py quality 116136641
  
  # Информация о треке
  python zvuk_multibot.py info 116136641             # Расширенная информация
  python zvuk_multibot.py ti 116136641               # Короткий алиас
  
  # Скачивание релиза (альбома)
  python zvuk_multibot.py dlr 22618641 -q flac
  python zvuk_multibot.py album 22618641
  
  # Тексты песен
  python zvuk_multibot.py txt 116136641              # Получить текст
  python zvuk_multibot.py text 116136641
  
  # Релизы артиста
  python zvuk_multibot.py art 102622 -l 20          # Первые 20 релизов
  python zvuk_multibot.py artist 102622

Полные команды (работают как раньше):
  python zvuk_multibot.py download-track 116136641 --quality flac
  python zvuk_multibot.py check-quality 116136641
  python zvuk_multibot.py track-info-extended 116136641
  
Флаги:
  -t, --token      Токен авторизации  
  -c, --config     Путь к конфигу
  -v, --verbose    Подробный вывод
  -q, --quality    Качество (flac/high/mid)
  -f, --filename   Имя файла
  -nm, --no-metadata  Без метаданных
  -nc, --no-cover     Без обложки
  -l, --limit      Лимит результатов

Конфигурация:
  Создайте файл config.json с токеном:
  {
      "auth_token": "ваш_токен_здесь"
  }
            """
        )
        
        parser.add_argument('--token', '-t', help='Токен аутентификации (если не указан, будет читаться из config.json)')
        parser.add_argument('--config', '-c', default='config.json', help='Путь к файлу конфигурации (по умолчанию config.json)')
        parser.add_argument('--verbose', '-v', action='store_true', help='Подробный вывод')
        
        subparsers = parser.add_subparsers(dest='command', help='Доступные команды')
        
        # Команда profile
        prof_parser = subparsers.add_parser('profile', aliases=['prof', 'p'], help='Получить информацию о профиле')
        
        # Команда download-track
        download_track_parser = subparsers.add_parser('download-track', aliases=['dl', 'download'], help='Скачать трек')
        download_track_parser.add_argument('track_id', type=int, help='ID трека')
        download_track_parser.add_argument('--quality', '-q', 
                                         default='high', help='Качество: f|h|m или flac|high|mid')
        download_track_parser.add_argument('--filename', '-f', help='Имя файла для сохранения')
        download_track_parser.add_argument('--no-metadata', '-nm', action='store_true', 
                                         help='Не внедрять метаданные')
        download_track_parser.add_argument('--no-cover', '-nc', action='store_true', 
                                         help='Не скачивать обложку')
        download_track_parser.add_argument('--save-lyrics', '-sl', action='store_true', 
                                         help='Сохранить текст рядом с файлом (.lrc при таймкодах, иначе .txt)')
        download_track_parser.add_argument('--save-subtitles', '-ss', action='store_true', 
                                         help='Сохранить субтитры .srt (на основе LRC) для VLC')
        
        # Команда check-quality
        check_quality_parser = subparsers.add_parser('check-quality', aliases=['chk', 'quality'], help='Проверить доступные качества')
        check_quality_parser.add_argument('track_id', type=int, help='ID трека')
        
        # Команда track-info-extended
        track_info_ext_parser = subparsers.add_parser('track-info-extended', aliases=['info', 'ti'], 
                                                     help='Расширенная информация о треке')
        track_info_ext_parser.add_argument('track_id', type=int, help='ID трека')
        
        # Команда download-release
        download_release_parser = subparsers.add_parser('download-release', aliases=['dlr', 'album'], help='Скачать релиз')
        download_release_parser.add_argument('release_id', type=int, help='ID релиза')
        download_release_parser.add_argument('--quality', '-q', 
                                           default='high', help='Качество: f|h|m или flac|high|mid')
        download_release_parser.add_argument('--save-lyrics', '-sl', action='store_true', 
                                           help='Сохранять тексты рядом с файлами (.lrc/.txt)')
        download_release_parser.add_argument('--save-subtitles', '-ss', action='store_true', 
                                           help='Сохранять .srt субтитры (если есть LRC)')
        
        # Команда track-info
        track_info_parser = subparsers.add_parser('track-info', aliases=['tinfo'], help='Информация о треке')
        track_info_parser.add_argument('track_ids', nargs='+', type=int, help='ID треков')
        
        # Команда release-info
        release_info_parser = subparsers.add_parser('release-info', aliases=['rinfo'], help='Информация о релизе')
        release_info_parser.add_argument('release_ids', nargs='+', type=int, help='ID релизов')
        
        # Команда release-info-extended (новая команда для детальной информации об альбоме)
        release_info_ext_parser = subparsers.add_parser('release-info-extended', aliases=['rext', 'album-info'], 
                                                       help='Расширенная информация о релизе (альбоме)')
        release_info_ext_parser.add_argument('release_id', type=int, help='ID релиза')
        
        # Команда check-release-quality (новая команда для проверки качества всех треков альбома)
        check_release_quality_parser = subparsers.add_parser('check-release-quality', aliases=['chkr', 'album-quality'], 
                                                            help='Проверить качества всех треков релиза')
        check_release_quality_parser.add_argument('release_id', type=int, help='ID релиза')
        
        # Команда lyrics
        lyrics_parser = subparsers.add_parser('lyrics', aliases=['txt', 'text'], help='Получить текст песни')
        lyrics_parser.add_argument('track_id', type=int, help='ID трека')
        
        # Команда artist-releases
        artist_releases_parser = subparsers.add_parser('artist-releases', aliases=['art', 'artist'], help='Релизы артиста')
        artist_releases_parser.add_argument('artist_id', type=int, help='ID артиста')
        artist_releases_parser.add_argument('--limit', '-l', type=int, default=50, help='Лимит результатов')
        
        # Команда artist-info (новая команда для детальной информации об артисте)
        artist_info_parser = subparsers.add_parser('artist-info', aliases=['ainfo', 'artist-detail'], 
                                                  help='Подробная информация об артисте с альбомами')
        artist_info_parser.add_argument('artist_id', type=int, help='ID артиста')
        artist_info_parser.add_argument('--limit', '-l', type=int, default=20, help='Лимит релизов для отображения')
        
        # Команда download-artist (новая команда для скачивания всех альбомов артиста)
        download_artist_parser = subparsers.add_parser('download-artist', aliases=['dla', 'artist-download'], 
                                                      help='Скачать все альбомы артиста')
        download_artist_parser.add_argument('artist_id', type=int, help='ID артиста')
        download_artist_parser.add_argument('--quality', '-q', default='high',
                                          help='Качество: f|h|m или flac|high|mid')
        download_artist_parser.add_argument('--limit', '-l', type=int, default=10, help='Максимальное количество альбомов')
        download_artist_parser.add_argument('--skip-singles', '-s', action='store_true', 
                                          help='Пропустить синглы и EP (только полные альбомы)')
        download_artist_parser.add_argument('--save-lyrics', '-sl', action='store_true', 
                                          help='Сохранять тексты рядом с файлами (.lrc/.txt)')
        download_artist_parser.add_argument('--save-subtitles', '-ss', action='store_true', 
                                          help='Сохранять .srt субтитры (если есть LRC)')
        
        # Команда artist-browser (новая команда для интерактивного просмотра артиста)
        artist_browser_parser = subparsers.add_parser('artist-browser', aliases=['browse', 'ab'], 
                                                     help='Интерактивный браузер альбомов артиста')
        artist_browser_parser.add_argument('artist_id', type=int, help='ID артиста')
        
        return parser
    
    async def run(self):
        """Основной метод запуска CLI"""
        args = self.parser.parse_args()
        
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Загружаем токен из конфига или аргументов
        auth_token = args.token
        
        # Пытаемся загрузить конфиг
        config_data = {}
        if args.config and os.path.exists(args.config):
            try:
                with open(args.config, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    logger.info(f"Конфигурация загружена из {args.config}")
            except Exception as e:
                logger.error(f"Ошибка загрузки конфигурации: {e}")
        
        # Если токен не передан через аргументы, берем из конфига
        if not auth_token and 'auth_token' in config_data:
            auth_token = config_data['auth_token']
            logger.info("Токен загружен из конфигурации")
        
        # Проверяем наличие токена
        if not auth_token:
            print("❌ Ошибка: Токен авторизации не найден!")
            print("Укажите токен через --token или добавьте его в config.json")
            print("Пример config.json:")
            print('{\n    "auth_token": "ваш_токен_здесь"\n}')
            sys.exit(1)
        
        # Создаем конфигурацию
        config = ZvukConfig(auth_token=auth_token)
        
        # Применяем дополнительные настройки из конфига
        for key, value in config_data.items():
            if hasattr(config, key) and key != 'auth_token':  # токен уже установлен
                setattr(config, key, value)
        
        # Запускаем бота
        async with ZvukMultiBot(config) as bot:
            await self.execute_command(bot, args)
    
    async def execute_command(self, bot: ZvukMultiBot, args):
        """Выполнение команды"""
        try:
            if args.command in ['profile', 'prof', 'p']:
                await self.cmd_profile(bot)
            
            elif args.command in ['download-track', 'dl', 'download']:
                await self.cmd_download_track(bot, args.track_id, args.quality, args.filename,
                                            not args.no_metadata, not args.no_cover, getattr(args, 'save_lyrics', False), getattr(args, 'save_subtitles', False))
            
            elif args.command in ['check-quality', 'chk', 'quality']:
                await self.cmd_check_quality(bot, args.track_id)
            
            elif args.command in ['track-info-extended', 'info', 'ti']:
                await self.cmd_track_info_extended(bot, args.track_id)
            
            elif args.command in ['download-release', 'dlr', 'album']:
                await self.cmd_download_release(bot, args.release_id, args.quality, getattr(args, 'save_lyrics', False), getattr(args, 'save_subtitles', False))
            
            elif args.command in ['track-info', 'tinfo']:
                await self.cmd_track_info(bot, args.track_ids)
            
            elif args.command in ['release-info', 'rinfo']:
                await self.cmd_release_info(bot, args.release_ids)
            
            elif args.command in ['release-info-extended', 'rext', 'album-info']:
                await self.cmd_release_info_extended(bot, args.release_id)
            
            elif args.command in ['check-release-quality', 'chkr', 'album-quality']:
                await self.cmd_check_release_quality(bot, args.release_id)
            
            elif args.command in ['lyrics', 'txt', 'text']:
                await self.cmd_lyrics(bot, args.track_id)
            
            elif args.command in ['artist-releases', 'art', 'artist']:
                await self.cmd_artist_releases(bot, args.artist_id, args.limit)
            
            elif args.command in ['artist-info', 'ainfo', 'artist-detail']:
                await self.cmd_artist_info(bot, args.artist_id, args.limit)
            
            elif args.command in ['download-artist', 'dla', 'artist-download']:
                await self.cmd_download_artist(bot, args.artist_id, args.quality, args.limit, args.skip_singles, getattr(args, 'save_lyrics', False), getattr(args, 'save_subtitles', False))
            
            elif args.command in ['artist-browser', 'browse', 'ab']:
                await self.cmd_artist_browser(bot, args.artist_id)
            
            else:
                self.parser.print_help()
        
        finally:
            bot.print_stats()
    
    async def cmd_profile(self, bot: ZvukMultiBot):
        """Команда получения профиля"""
        profile = await bot.get_profile()
        if profile:
            print(json.dumps(profile, indent=2, ensure_ascii=False))
        else:
            print("Не удалось получить информацию о профиле")
    
    async def cmd_download_track(self, bot: ZvukMultiBot, track_id: int, 
                               quality: str, filename: str, embed_metadata: bool = True,
                               download_cover: bool = True, save_lyrics: bool = False, save_subtitles: bool = False):
        """Команда скачивания трека"""
        norm_q = self.normalize_quality(quality)
        success = await bot.download_track(track_id, norm_q, filename, embed_metadata, download_cover, save_lyrics=save_lyrics, save_subtitles=save_subtitles)
        if success:
            print(f"Трек {track_id} успешно скачан")
            if embed_metadata:
                print("✅ Метаданные внедрены")
            if download_cover:
                print("✅ Обложка добавлена")
        else:
            print(f"Не удалось скачать трек {track_id}")
    
    async def cmd_check_quality(self, bot: ZvukMultiBot, track_id: int):
        """Команда проверки качеств"""
        quality_results = await bot.check_track_qualities(track_id)
        report = bot.quality_checker.format_quality_report(track_id, quality_results)
        print(report)
    
    async def cmd_track_info_extended(self, bot: ZvukMultiBot, track_id: int):
        """Команда получения расширенной информации о треке"""
        track_data = await bot.get_track_with_quality_info(track_id)
        if track_data:
            # Основная информация
            print(f"\n🎵 {track_data.get('artist_names', ['Unknown'])[0]} - {track_data.get('title', 'Unknown')}")
            print(f"📀 Альбом: {track_data.get('release_title', 'Unknown')}")
            print(f"⏱️ Длительность: {track_data.get('duration', 0)} сек")
            print(f"🎭 Жанры: {', '.join(track_data.get('genres', []))}")
            print(f"🔞 Explicit: {'Да' if track_data.get('explicit') else 'Нет'}")
            print(f"📝 Есть текст: {'Да' if track_data.get('lyrics') else 'Нет'}")
            print(f"💿 FLAC доступен: {'Да' if track_data.get('has_flac') else 'Нет'}")
            
            # Информация о качествах
            if 'quality_check' in track_data:
                quality_results = track_data['quality_check']
                report = bot.quality_checker.format_quality_report(track_id, quality_results)
                print(report)
            
            # Оценки размеров
            if 'estimated_sizes' in track_data:
                print(f"\n📏 Оценочные размеры файлов:")
                for quality, size in track_data['estimated_sizes'].items():
                    print(f"  {quality.upper()}: {size}")
            
            # Рекомендация
            if track_data.get('recommended_quality'):
                print(f"\n🏆 Рекомендуемое качество: {track_data['recommended_quality'].upper()}")
            
        else:
            print(f"Не удалось получить информацию о треке {track_id}")
    
    async def cmd_download_release(self, bot: ZvukMultiBot, release_id: int, quality: str, save_lyrics: bool = False, save_subtitles: bool = False):
        """Команда скачивания релиза"""
        norm_q = self.normalize_quality(quality)
        count = await bot.download_release(release_id, norm_q, save_lyrics=save_lyrics, save_subtitles=save_subtitles)
        print(f"Скачано {count} треков из релиза {release_id}")
    
    async def cmd_track_info(self, bot: ZvukMultiBot, track_ids: List[int]):
        """Команда получения информации о треках"""
        info = await bot.get_tracks(track_ids)
        if info:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print("Не удалось получить информацию о треках")
    
    async def cmd_release_info(self, bot: ZvukMultiBot, release_ids: List[int]):
        """Команда получения информации о релизах"""
        info = await bot.get_releases(release_ids)
        if info:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print("Не удалось получить информацию о релизах")
    
    async def cmd_lyrics(self, bot: ZvukMultiBot, track_id: int):
        """Команда получения текста песни"""
        lyrics = await bot.get_lyrics(track_id)
        if lyrics:
            print(f"Текст песни для трека {track_id}:")
            print("-" * 40)
            print(lyrics)
        else:
            print(f"Текст для трека {track_id} не найден")
    
    async def cmd_artist_releases(self, bot: ZvukMultiBot, artist_id: int, limit: int):
        """Команда получения релизов артиста"""
        releases = await bot.get_artist_releases(artist_id, limit)
        if releases:
            print(f"Релизы артиста {artist_id}:")
            for release_id in releases:
                print(f"  - {release_id}")
            print(f"Всего: {len(releases)} релизов")
        else:
            print(f"Релизы артиста {artist_id} не найдены")
    
    async def cmd_release_info_extended(self, bot: ZvukMultiBot, release_id: int):
        """Расширенная информация о релизе с форматированием"""
        release_info = await bot.get_releases([release_id])
        if not release_info or 'result' not in release_info or 'releases' not in release_info['result']:
            print(f"Релиз {release_id} не найден")
            return
        
        releases = release_info['result']['releases']
        if str(release_id) not in releases:
            print(f"Релиз {release_id} не найден")
            return
        
        release = releases[str(release_id)]
        tracks_data = release_info['result'].get('tracks', {})
        
        print(f"🎵 Альбом: {release.get('title', 'Без названия')}")
        artist_names = release.get('artist_names', [])
        if artist_names:
            print(f"👤 Исполнитель: {', '.join(artist_names)}")
        
        # Парсим дату
        date_val = release.get('date')
        if date_val:
            date_str = str(date_val)
            if len(date_str) == 8:  # YYYYMMDD
                year = date_str[:4]
                month = date_str[4:6]
                day = date_str[6:8]
                print(f"📅 Дата выпуска: {day}.{month}.{year}")
            else:
                print(f"📅 Дата: {date_val}")
        
        print(f"🆔 ID: {release_id}")
        print(f"💿 Тип: {release.get('type', 'неизвестен')}")
        
        # Получаем треки по их ID из релиза
        track_ids = release.get('track_ids', [])
        if track_ids and tracks_data:
            print(f"\n📀 Треки ({len(track_ids)}):")
            total_duration = 0
            
            # Создаем список треков с их позициями
            tracks_with_positions = []
            for track_id in track_ids:
                if str(track_id) in tracks_data:
                    track = tracks_data[str(track_id)]
                    tracks_with_positions.append(track)
            
            # Сортируем по позиции
            tracks_with_positions.sort(key=lambda x: x.get('position', 0))
            
            for track in tracks_with_positions:
                position = track.get('position', 0)
                title = track.get('title', 'Без названия')
                duration = track.get('duration', 0)
                total_duration += duration
                has_flac = track.get('has_flac', False)
                explicit = track.get('explicit', False)
                
                # Форматирование времени
                minutes, seconds = divmod(duration, 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
                
                # Иконки
                quality_icon = "🎼" if has_flac else "🎵"
                explicit_icon = "🔞" if explicit else ""
                
                print(f"  {position:2d}. {title} [{time_str}] {quality_icon}{explicit_icon}")
            
            # Общая продолжительность
            total_minutes, total_seconds = divmod(total_duration, 60)
            total_hours, total_minutes = divmod(total_minutes, 60)
            if total_hours > 0:
                duration_str = f"{total_hours}:{total_minutes:02d}:{total_seconds:02d}"
            else:
                duration_str = f"{total_minutes:02d}:{total_seconds:02d}"
            
            print(f"\n⏱️  Общая продолжительность: {duration_str}")
            
            # Статистика качества
            flac_count = sum(1 for track in tracks_with_positions if track.get('has_flac', False))
            explicit_count = sum(1 for track in tracks_with_positions if track.get('explicit', False))
            
            print(f"📊 Статистика:")
            print(f"   🎼 FLAC доступен: {flac_count}/{len(tracks_with_positions)} треков")
            if explicit_count > 0:
                print(f"   🔞 Explicit контент: {explicit_count} треков")
        else:
            print("Треки не найдены")
    
    async def cmd_check_release_quality(self, bot: ZvukMultiBot, release_id: int):
        """Проверка доступности качества для всех треков релиза"""
        release_info = await bot.get_releases([release_id])
        if not release_info or 'result' not in release_info or 'releases' not in release_info['result']:
            print(f"Релиз {release_id} не найден")
            return
        
        releases = release_info['result']['releases']
        if str(release_id) not in releases:
            print(f"Релиз {release_id} не найден")
            return
        
        release = releases[str(release_id)]
        tracks_data = release_info['result'].get('tracks', {})
        track_ids = release.get('track_ids', [])
        
        if not track_ids:
            print("Треки в релизе не найдены")
            return
        
        print(f"🔍 Проверка качества для альбома: {release.get('title', 'Без названия')}")
        print(f"📊 Треков для проверки: {len(track_ids)}")
        print("-" * 60)
        
        # Статистика по качеству
        quality_stats = {'lossless': 0, 'high': 0, 'mid': 0, 'unavailable': 0}
        
        # Создаем список треков с их позициями
        tracks_with_positions = []
        for track_id in track_ids:
            if str(track_id) in tracks_data:
                track = tracks_data[str(track_id)]
                tracks_with_positions.append(track)
        
        # Сортируем по позиции
        tracks_with_positions.sort(key=lambda x: x.get('position', 0))
        
        for track in tracks_with_positions:
            track_id = track.get('id')
            title = track.get('title', 'Без названия')
            position = track.get('position', 0)
            has_flac = track.get('has_flac', False)
            highest_quality = track.get('highest_quality', '')
            
            if not track_id:
                print(f"  {position:2d}. {title[:40]:<40} ❌ ID не найден")
                quality_stats['unavailable'] += 1
                continue
            
            # Анализируем доступное качество из данных
            quality_icons = []
            
            if has_flac or highest_quality == 'flac':
                quality_icons.append("🎼 FLAC")
                quality_stats['lossless'] += 1
            
            # Для MP3 качества нужно получить детальную информацию о треке
            track_info = await bot.get_tracks([track_id])
            if track_info and 'result' in track_info and 'tracks' in track_info['result']:
                track_detail = track_info['result']['tracks'].get(str(track_id))
                if track_detail:
                    files = track_detail.get('files', [])
                    
                    has_320k = any(f.get('bitrate') == 320000 and f.get('codec') == 'mp3' for f in files)
                    has_128k = any(f.get('bitrate') == 128000 and f.get('codec') == 'mp3' for f in files)
                    
                    if has_320k:
                        quality_icons.append("🎵 320k")
                        quality_stats['high'] += 1
                    if has_128k:
                        quality_icons.append("🎶 128k")
                        quality_stats['mid'] += 1
            
            if quality_icons:
                quality_str = " | ".join(quality_icons)
                print(f"  {position:2d}. {title[:40]:<40} ✅ {quality_str}")
            else:
                print(f"  {position:2d}. {title[:40]:<40} ❌ Нет доступных форматов")
                quality_stats['unavailable'] += 1
        
        # Итоговая статистика
        print("-" * 60)
        print("📈 Статистика качества:")
        if quality_stats['lossless'] > 0:
            print(f"  🎼 FLAC (lossless): {quality_stats['lossless']} треков")
        if quality_stats['high'] > 0:
            print(f"  🎵 MP3 320k: {quality_stats['high']} треков")
        if quality_stats['mid'] > 0:
            print(f"  🎶 MP3 128k: {quality_stats['mid']} треков")
        if quality_stats['unavailable'] > 0:
            print(f"  ❌ Недоступно: {quality_stats['unavailable']} треков")
        
        # Рекомендация
        total_available = sum(quality_stats.values()) - quality_stats['unavailable']
        if total_available == len(track_ids):
            print("✅ Все треки доступны для скачивания!")
        elif total_available > 0:
            print(f"⚠️  Доступно {total_available} из {len(track_ids)} треков")
        else:
            print("❌ Ни один трек недоступен для скачивания")
    
    async def cmd_artist_info(self, bot: ZvukMultiBot, artist_id: int, limit: int):
        """Подробная информация об артисте с альбомами"""
        # Получаем релизы артиста
        releases = await bot.get_artist_releases(artist_id, limit)
        if not releases:
            print(f"❌ Релизы артиста {artist_id} не найдены")
            return
        
        print(f"🎤 ИНФОРМАЦИЯ ОБ АРТИСТЕ {artist_id}")
        print("=" * 60)
        
        # Получаем информацию о релизах БЕЗ треков (чтобы избежать ошибки API)
        release_info = await bot.get_releases(releases[:limit], include_tracks=False)
        if not release_info or 'result' not in release_info:
            print("❌ Не удалось получить подробную информацию о релизах")
            return
        
        releases_data = release_info['result'].get('releases', {})
        
        # Сбор статистики
        total_albums = 0
        total_releases = len(releases_data)
        years = set()
        
        print(f"📀 АЛЬБОМЫ И РЕЛИЗЫ ({total_releases}):")
        print("-" * 60)
        
        # Сортируем релизы по году (если есть дата)
        sorted_releases = []
        for release_id, release_data in releases_data.items():
            date_val = release_data.get('date', 0)
            year = 0
            if date_val:
                date_str = str(date_val)
                if len(date_str) >= 4:
                    try:
                        year = int(date_str[:4])
                    except ValueError:
                        year = 0
            sorted_releases.append((year, release_id, release_data))
        
        # Сортируем по году (новые сначала)
        sorted_releases.sort(key=lambda x: x[0], reverse=True)
        
        for year, release_id, release_data in sorted_releases:
            title = release_data.get('title', 'Без названия')
            track_ids = release_data.get('track_ids', [])
            release_type = release_data.get('type', 'unknown')
            
            # Иконка типа релиза
            type_icon = "💿" if release_type == "album" else "🎵" if release_type == "single" else "📀"
            year_str = f"{year}" if year > 0 else "????"
            
            # Используем количество треков из track_ids
            track_count = len(track_ids)
            
            print(f"  {type_icon} {year_str} | {title:<35} | {track_count:2d} треков | ID: {release_id}")
            
            # Статистика
            if release_type == "album" or track_count >= 7:  # Альбомом считаем от 7 треков
                total_albums += 1
            if year > 0:
                years.add(year)
        
        print("-" * 60)
        print(f"📊 СТАТИСТИКА:")
        print(f"   💿 Альбомов: {total_albums}")
        print(f"   🎵 Всего релизов: {total_releases}")
        if years:
            print(f"   📅 Годы активности: {min(years)}-{max(years)}")
        
        print(f"\n💡 КОМАНДЫ ДЛЯ РАБОТЫ:")
        print(f"   python zvuk_multibot.py dla {artist_id} -q flac -l 5   # Скачать 5 альбомов")
        print(f"   python zvuk_multibot.py browse {artist_id}             # Интерактивный выбор")
        print(f"   python zvuk_multibot.py rext RELEASE_ID               # Подробности альбома")
    
    async def cmd_download_artist(self, bot: ZvukMultiBot, artist_id: int, quality: str, limit: int, skip_singles: bool, save_lyrics: bool = False, save_subtitles: bool = False):
        """Скачивание всех альбомов артиста"""
        print(f"🎤 Скачивание альбомов артиста {artist_id}")
        
        # Получаем релизы
        releases = await bot.get_artist_releases(artist_id, limit * 2)  # Берем больше для фильтрации
        if not releases:
            print(f"❌ Релизы артиста {artist_id} не найдены")
            return
        
        # Получаем информацию о релизах для фильтрации
        release_info = await bot.get_releases(releases, include_tracks=False)
        if not release_info or 'result' not in release_info:
            print("❌ Не удалось получить информацию о релизах")
            return
        
        releases_data = release_info['result'].get('releases', {})
        
        # Фильтруем релизы
        albums_to_download = []
        for release_id, release_data in releases_data.items():
            release_type = release_data.get('type', '')
            track_count = len(release_data.get('track_ids', []))
            
            # Фильтр для альбомов
            if skip_singles:
                if release_type == 'album' or track_count >= 7:  # Считаем альбомом от 7 треков
                    albums_to_download.append((int(release_id), release_data))
            else:
                albums_to_download.append((int(release_id), release_data))
        
        # Сортируем по дате выхода (новые СНАЧАЛА), затем ограничиваем количество
        def _release_date_int(data: Dict) -> int:
            dv = data.get('date')
            if dv is None:
                return 99999999
            ds = str(dv)
            # ожидаемый формат YYYYMMDD, но берём первые 8 цифр на всякий случай
            ds = ''.join(ch for ch in ds if ch.isdigit())[:8]
            try:
                return int(ds) if ds else 99999999
            except ValueError:
                return 99999999

        albums_to_download.sort(key=lambda pair: _release_date_int(pair[1]), reverse=True)
        albums_to_download = albums_to_download[:limit]
        
        if not albums_to_download:
            print("❌ Не найдено альбомов для скачивания")
            return
        
        print(f"📀 Найдено {len(albums_to_download)} релизов для скачивания")
        norm_q = self.normalize_quality(quality)
        print(f"🎵 Качество: {norm_q.upper()}")
        print("=" * 60)
        
        # Скачиваем альбомы
        success_count = 0
        for i, (release_id, release_data) in enumerate(albums_to_download, 1):
            title = release_data.get('title', 'Без названия')
            track_count = len(release_data.get('track_ids', []))
            
            print(f"\n🔄 [{i}/{len(albums_to_download)}] Скачивание: {title} ({track_count} треков)")
            
            success = await bot.download_release(release_id, norm_q, save_lyrics=save_lyrics, save_subtitles=save_subtitles, album_index=i)
            if success:
                print(f"✅ Альбом '{title}' скачан успешно")
                success_count += 1
            else:
                print(f"❌ Ошибка при скачивании альбома '{title}'")
        
        print("\n" + "=" * 60)
        print(f"📊 РЕЗУЛЬТАТ: {success_count}/{len(albums_to_download)} альбомов скачано успешно")
    
    def normalize_quality(self, quality: str) -> str:
        q = (quality or '').strip().lower()
        mapping = {
            'f': 'flac',
            'h': 'high',
            'm': 'mid',
            'flac': 'flac',
            'high': 'high',
            'mid': 'mid',
            '320': 'high',
            '128': 'mid'
        }
        return mapping.get(q, 'high')
    
    async def cmd_artist_browser(self, bot: ZvukMultiBot, artist_id: int):
        """Интерактивный браузер альбомов артиста"""
        print(f"🎤 Интерактивный браузер артиста {artist_id}")
        print("=" * 60)
        
        # Получаем релизы
        releases = await bot.get_artist_releases(artist_id, 50)
        if not releases:
            print(f"❌ Релизы артиста {artist_id} не найдены")
            return
        
        # Получаем информацию о релизах
        release_info = await bot.get_releases(releases, include_tracks=False)
        if not release_info or 'result' not in release_info:
            print("❌ Не удалось получить информацию о релизах")
            return
        
        releases_data = release_info['result'].get('releases', {})
        
        # Подготавливаем список для отображения
        release_list = []
        for release_id, release_data in releases_data.items():
            title = release_data.get('title', 'Без названия')
            track_count = len(release_data.get('track_ids', []))
            release_type = release_data.get('type', 'unknown')
            date_val = release_data.get('date', 0)
            
            year = "????"
            if date_val:
                date_str = str(date_val)
                if len(date_str) >= 4:
                    try:
                        year = date_str[:4]
                    except ValueError:
                        pass
            
            type_icon = "💿" if release_type == "album" else "🎵" if release_type == "single" else "📀"
            
            release_list.append({
                'id': int(release_id),
                'title': title,
                'year': year,
                'tracks': track_count,
                'type': release_type,
                'icon': type_icon
            })
        
        # Сортируем по году (новые сначала)
        release_list.sort(key=lambda x: x['year'], reverse=True)
        
        print("📀 ДОСТУПНЫЕ РЕЛИЗЫ:")
        print("-" * 60)
        for i, release in enumerate(release_list, 1):
            print(f"{i:2d}. {release['icon']} {release['year']} | {release['title']:<35} | {release['tracks']:2d} треков")
        
        print("\n💡 КОМАНДЫ:")
        print("   Введите номер релиза для подробной информации")
        print("   Введите 'q' для выхода")
        print("   Введите 'help' для справки")
        
        # Здесь можно добавить интерактивность с input(), но для демонстрации покажем справку
        print("\n🔧 БЫСТРЫЕ КОМАНДЫ ДЛЯ СКАЧИВАНИЯ:")
        for i, release in enumerate(release_list[:5], 1):  # Показываем первые 5
            print(f"   python zvuk_multibot.py dlr {release['id']} -q flac    # {release['title']}")

def main():
    """Главная функция"""
    cli = ZvukMultiBotCLI()
    
    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
