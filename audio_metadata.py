#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для работы с метаданными и обложками треков
"""

import os
import asyncio
import aiohttp
import io
import datetime
import re
from pathlib import Path
from typing import Dict, Optional, Tuple, List
import logging

try:
    from mutagen.flac import FLAC, Picture
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON, TRCK, TPE2, SYLT, USLT
    from mutagen.id3._util import ID3NoHeaderError
    import mutagen.flac
    from PIL import Image
    METADATA_AVAILABLE = True
except ImportError:
    METADATA_AVAILABLE = False
    logging.warning("Библиотеки для метаданных не установлены. Установите: pip install mutagen pillow")

logger = logging.getLogger(__name__)

class AudioMetadataManager:
    """Менеджер для работы с метаданными аудиофайлов"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def download_cover_art(self, cover_url: str, size: str = "1000x1000") -> Optional[bytes]:
        """Скачивание обложки альбома"""
        try:
            # Подставляем нужный размер в URL
            formatted_url = cover_url.format(size=size)
            logger.info(f"Скачивание обложки: {formatted_url}")
            
            async with self.session.get(formatted_url) as response:
                if response.status == 200:
                    cover_data = await response.read()
                    logger.info(f"Обложка скачана: {len(cover_data)} байт")
                    return cover_data
                else:
                    logger.error(f"Ошибка скачивания обложки: HTTP {response.status}")
        
        except Exception as e:
            logger.error(f"Исключение при скачивании обложки: {e}")
        
        return None
    
    def optimize_cover_image(self, image_data: bytes, max_size: Tuple[int, int] = (1000, 1000)) -> bytes:
        """Оптимизация изображения обложки"""
        if not METADATA_AVAILABLE:
            return image_data
        
        try:
            # Открываем изображение
            with Image.open(io.BytesIO(image_data)) as img:
                # Конвертируем в RGB если нужно
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Изменяем размер если нужно
                if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                
                # Сохраняем в буфер
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=90, optimize=True)
                optimized_data = output.getvalue()
                
                logger.info(f"Обложка оптимизирована: {len(image_data)} -> {len(optimized_data)} байт")
                return optimized_data
        
        except Exception as e:
            logger.error(f"Ошибка оптимизации обложки: {e}")
            return image_data

    def split_lyrics_formats(self, lyrics_raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Определяет, содержит ли текст синхронизированные таймкоды (LRC) и разделяет форматы.

        Возвращает кортеж: (plain_text, lrc_text)
        """
        if not lyrics_raw:
            return None, None

        # Признак строк LRC вида [mm:ss.xx] или [mm:ss]
        has_lrc = bool(re.search(r"\[\s*\d{1,2}:\d{2}(?:[\.:]\d{1,2})?\s*\]", lyrics_raw))

        if has_lrc:
            lrc_text = self._normalize_lrc(lyrics_raw)
            plain_text = self._lrc_to_plain(lrc_text)
            return plain_text, lrc_text

        return lyrics_raw, None

    def _normalize_lrc(self, lyrics_lrc: str) -> str:
        """Нормализует LRC: приводит таймкоды к [mm:ss.xx], удаляет пустые строки в начале/конце."""
        lines = lyrics_lrc.splitlines()
        normalized_lines: List[str] = []
        for line in lines:
            # Оставляем как есть строки с таймкодом
            if re.search(r"\[\s*\d{1,2}:\d{2}(?:[\.:]\d{1,2})?\s*\]", line):
                # Приводим 00:00.0 к 00:00.00
                def repl(m: re.Match) -> str:
                    ts = m.group(0)
                    ts = ts.replace('[', '').replace(']', '').strip()
                    parts = re.split(r"[:\.]", ts)
                    mm = int(parts[0]) if parts and parts[0].isdigit() else 0
                    ss = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                    ff = 0
                    if len(parts) > 2 and parts[2].isdigit():
                        ff = int(parts[2])
                        # ограничим до двух знаков
                        ff = max(0, min(ff, 99))
                    return f"[{mm:02d}:{ss:02d}.{ff:02d}]"

                line = re.sub(r"\[\s*\d{1,2}:\d{2}(?:[\.:]\d{1,2})?\s*\]", repl, line, count=1)
                normalized_lines.append(line)
            else:
                normalized_lines.append(line)
        # Удаляем ведущие/замыкающие пустые строки
        while normalized_lines and not normalized_lines[0].strip():
            normalized_lines.pop(0)
        while normalized_lines and not normalized_lines[-1].strip():
            normalized_lines.pop()
        return "\n".join(normalized_lines)

    def _lrc_to_plain(self, lyrics_lrc: str) -> str:
        """Преобразует LRC в обычный текст без таймкодов."""
        plain_lines: List[str] = []
        for line in lyrics_lrc.splitlines():
            text = re.sub(r"^\s*\[[^\]]+\]\s*", "", line)
            plain_lines.append(text)
        return "\n".join(plain_lines)

    def lrc_to_srt(self, lyrics_lrc: str) -> str:
        """Конвертирует LRC в SubRip (.srt) для VLC.

        Каждая метка времени превращается в отдельный субтитр. Конец сегмента —
        время следующего сегмента минус 0.5 секунды. Если следующего нет — +4 секунды.
        """
        # Собираем пары (time_ms, text)
        entries: List[Tuple[int, str]] = []
        time_pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:[\.:](\d{1,2}))?\]")

        for raw_line in lyrics_lrc.splitlines():
            if not raw_line.strip():
                continue
            times = list(time_pattern.finditer(raw_line))
            if not times:
                continue
            # Текст без первой метки времени в начале
            text = time_pattern.sub("", raw_line).strip()
            if not text:
                text = "♪"
            for m in times:
                mm = int(m.group(1) or 0)
                ss = int(m.group(2) or 0)
                ff = int(m.group(3) or 0)
                # ff трактуем как сотые доли секунды
                ms = ff * 10 if ff < 10 else ff if ff < 100 else 0
                total_ms = (mm * 60 + ss) * 1000 + ms
                entries.append((total_ms, text))

        if not entries:
            # Если LRC не распознан, вернём пустую строку
            return ""

        entries.sort(key=lambda x: x[0])

        def fmt_srt_time(ms: int) -> str:
            if ms < 0:
                ms = 0
            h = ms // 3600000
            ms %= 3600000
            m = ms // 60000
            ms %= 60000
            s = ms // 1000
            ms %= 1000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        srt_lines: List[str] = []
        for idx, (start_ms, text) in enumerate(entries, start=1):
            if idx < len(entries):
                # Конец — на 0.5 секунды раньше следующего старта
                end_ms = max(start_ms + 500, entries[idx][0] - 500)
            else:
                end_ms = start_ms + 4000
            srt_lines.append(str(idx))
            srt_lines.append(f"{fmt_srt_time(start_ms)} --> {fmt_srt_time(end_ms)}")
            srt_lines.append(text)
            srt_lines.append("")

        return "\n".join(srt_lines)
    
    def embed_metadata_flac(self, file_path: Path, track_data: Dict, lyrics: str = None, cover_data: bytes = None, lyrics_lrc: str = None):
        """Внедрение метаданных в FLAC файл"""
        if not METADATA_AVAILABLE:
            logger.warning("Библиотеки метаданных недоступны")
            return False
        
        try:
            audio = FLAC(file_path)
            
            # Очищаем существующие метаданные
            audio.clear()
            
            # Основные метаданные
            if track_data.get('title'):
                audio['TITLE'] = track_data['title']
            
            if track_data.get('artist_names'):
                audio['ARTIST'] = track_data['artist_names'][0]
                audio['ALBUMARTIST'] = track_data['artist_names'][0]
            
            if track_data.get('release_title'):
                audio['ALBUM'] = track_data['release_title']
            
            if track_data.get('position'):
                audio['TRACKNUMBER'] = str(track_data['position'])
            
            if track_data.get('genres'):
                audio['GENRE'] = track_data['genres'][0]
            
            # Дополнительные метаданные
            if track_data.get('credits'):
                audio['ALBUMARTIST'] = track_data['credits']
            
            # Пишем LRC с таймкодами прямо в LYRICS, если доступно; иначе обычный текст
            if lyrics_lrc:
                audio['LYRICS'] = lyrics_lrc
                logger.info("LRC (с таймкодами) встроен в FLAC (LYRICS)")
            elif lyrics:
                audio['LYRICS'] = lyrics
                logger.info("Обычный текст (LYRICS) встроен в FLAC")
            
            # Внедряем обложку
            if cover_data:
                # Создаем картинку для FLAC
                picture = mutagen.flac.Picture()
                picture.type = 3  # Cover (front)
                picture.mime = 'image/jpeg'
                picture.desc = 'Cover'
                picture.data = cover_data
                
                audio.add_picture(picture)
                logger.info("Обложка добавлена в метаданные")
            
            # Сохраняем
            audio.save()
            logger.info(f"Метаданные сохранены в FLAC: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка внедрения метаданных в FLAC: {e}")
            return False
    
    def embed_metadata_mp3(self, file_path: Path, track_data: Dict, lyrics: str = None, cover_data: bytes = None, lyrics_lrc: str = None):
        """Внедрение метаданных в MP3 файл"""
        if not METADATA_AVAILABLE:
            logger.warning("Библиотеки метаданных недоступны")
            return False
        
        try:
            # Загружаем MP3 файл
            try:
                audio = MP3(file_path, ID3=ID3)
            except ID3NoHeaderError:
                # Создаем ID3 тег если его нет
                audio = MP3(file_path)
                audio.add_tags()
            
            # Очищаем существующие теги
            audio.delete()
            audio.add_tags()
            
            # Основные метаданные
            if track_data.get('title'):
                audio.tags.add(TIT2(encoding=3, text=track_data['title']))
            
            if track_data.get('artist_names'):
                audio.tags.add(TPE1(encoding=3, text=track_data['artist_names'][0]))
                audio.tags.add(TPE2(encoding=3, text=track_data['artist_names'][0]))
            
            if track_data.get('release_title'):
                audio.tags.add(TALB(encoding=3, text=track_data['release_title']))
            
            if track_data.get('position'):
                audio.tags.add(TRCK(encoding=3, text=str(track_data['position'])))
            
            if track_data.get('genres'):
                audio.tags.add(TCON(encoding=3, text=track_data['genres'][0]))
            
            # Встраиваем синхронизированный текст (SYLT) из LRC, если доступно; иначе обычный USLT
            if lyrics_lrc:
                try:
                    sylt_items: List[Tuple[str, int]] = []
                    time_pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:[\.:](\d{1,2}))?\]")
                    for raw_line in lyrics_lrc.splitlines():
                        if not raw_line.strip():
                            continue
                        times = list(time_pattern.finditer(raw_line))
                        if not times:
                            continue
                        text = time_pattern.sub("", raw_line).strip() or "♪"
                        for m in times:
                            mm = int(m.group(1) or 0)
                            ss = int(m.group(2) or 0)
                            ff = int(m.group(3) or 0)
                            ms = ff * 10 if ff < 10 else ff if ff < 100 else 0
                            total_ms = (mm * 60 + ss) * 1000 + ms
                            sylt_items.append((text, total_ms))
                    if sylt_items:
                        audio.tags.add(SYLT(encoding=3, lang='rus', format=2, type=1, desc='', text=sylt_items))
                        logger.info("Синхронизированный текст (SYLT) встроен в MP3")
                        # Добавим также USLT с тем же текстом (в виде LRC), чтобы редакторы его видели
                        audio.tags.add(USLT(encoding=3, lang='rus', desc='LRC', text=lyrics_lrc))
                        logger.info("Дублирующий USLT (LRC как текст) добавлен для видимости")
                except Exception as e:
                    logger.warning(f"Не удалось встроить SYLT: {e}")
            elif lyrics:
                from mutagen.id3 import USLT
                audio.tags.add(USLT(encoding=3, lang='rus', desc='', text=lyrics))
                logger.info("Обычный текст (USLT) встроен в MP3")
            
            # Внедряем обложку
            if cover_data:
                audio.tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,  # Cover (front)
                    desc='Cover',
                    data=cover_data
                ))
                logger.info("Обложка добавлена в метаданные")
            
            # Сохраняем
            audio.save()
            logger.info(f"Метаданные сохранены в MP3: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка внедрения метаданных в MP3: {e}")
            return False
    
    def embed_metadata(self, file_path: Path, track_data: Dict, lyrics: str = None, cover_data: bytes = None, lyrics_lrc: str = None):
        """Универсальное внедрение метаданных"""
        if not file_path.exists():
            logger.error(f"Файл не найден: {file_path}")
            return False
        
        file_extension = file_path.suffix.lower()
        
        if file_extension == '.flac':
            return self.embed_metadata_flac(file_path, track_data, lyrics, cover_data, lyrics_lrc)
        elif file_extension == '.mp3':
            return self.embed_metadata_mp3(file_path, track_data, lyrics, cover_data, lyrics_lrc)
        else:
            logger.warning(f"Неподдерживаемый формат файла: {file_extension}")
            return False

class QualityChecker:
    """Проверка доступных качеств для трека"""
    
    def __init__(self, session: aiohttp.ClientSession, base_url: str):
        self.session = session
        self.base_url = base_url
        self.qualities = ['flac', 'high', 'mid']
        self.quality_info = {
            'flac': {'format': 'FLAC', 'bitrate': 'Lossless', 'ext': 'flac'},
            'high': {'format': 'MP3', 'bitrate': '320 kbps', 'ext': 'mp3'},
            'mid': {'format': 'MP3', 'bitrate': '128 kbps', 'ext': 'mp3'}
        }
    
    async def check_quality_availability(self, track_id: int, quality: str) -> Dict:
        """Проверка доступности конкретного качества"""
        try:
            url = f"{self.base_url}/api/tiny/track/stream"
            params = {'id': track_id, 'quality': quality}
            
            # Добавляем небольшую задержку
            await asyncio.sleep(0.5)
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'result' in data and 'stream' in data['result']:
                        return {
                            'available': True,
                            'stream_url': data['result']['stream'],
                            'expires': data['result'].get('expire'),
                            'quality_info': self.quality_info.get(quality, {})
                        }
                
                return {
                    'available': False,
                    'error': f"HTTP {response.status}",
                    'quality_info': self.quality_info.get(quality, {})
                }
        
        except Exception as e:
            return {
                'available': False,
                'error': str(e),
                'quality_info': self.quality_info.get(quality, {})
            }
    
    async def check_all_qualities(self, track_id: int) -> Dict[str, Dict]:
        """Проверка всех доступных качеств для трека"""
        logger.info(f"Проверка доступных качеств для трека {track_id}")
        
        results = {}
        
        for quality in self.qualities:
            result = await self.check_quality_availability(track_id, quality)
            results[quality] = result
            
            status = "✅ Доступно" if result['available'] else "❌ Недоступно"
            quality_info = result['quality_info']
            logger.info(f"  {quality.upper()}: {status} ({quality_info.get('format', 'Unknown')} {quality_info.get('bitrate', '')})")
        
        return results
    
    def get_best_available_quality(self, quality_results: Dict[str, Dict]) -> Optional[str]:
        """Получение лучшего доступного качества"""
        # Порядок предпочтения: flac -> high -> mid
        for quality in ['flac', 'high', 'mid']:
            if quality_results.get(quality, {}).get('available', False):
                return quality
        return None
    
    def format_quality_report(self, track_id: int, quality_results: Dict[str, Dict]) -> str:
        """Форматирование отчета о качествах"""
        report = [f"\n📊 Доступные качества для трека {track_id}:"]
        report.append("=" * 50)
        
        for quality, result in quality_results.items():
            quality_info = result['quality_info']
            format_name = quality_info.get('format', 'Unknown')
            bitrate = quality_info.get('bitrate', '')
            
            if result['available']:
                status = "✅ Доступно"
                if result.get('expires'):
                    # Форматируем timestamp в читаемую дату
                    expires_timestamp = result['expires']
                    if isinstance(expires_timestamp, (int, str)) and str(expires_timestamp).isdigit():
                        expires_dt = datetime.datetime.fromtimestamp(int(expires_timestamp) / 1000)
                        expires_info = f" (действует до {expires_dt.strftime('%d.%m.%Y %H:%M')})"
                    else:
                        expires_info = f" (до {expires_timestamp})"
                else:
                    expires_info = ""
                report.append(f"  {quality.upper()}: {status} - {format_name} {bitrate}{expires_info}")
            else:
                status = "❌ Недоступно"
                error = result.get('error', 'Unknown error')
                report.append(f"  {quality.upper()}: {status} - {error}")
        
        best_quality = self.get_best_available_quality(quality_results)
        if best_quality:
            report.append(f"\n🏆 Рекомендуемое качество: {best_quality.upper()}")
        else:
            report.append(f"\n❌ Нет доступных качеств")
        
        return "\n".join(report)

# Функции-утилиты
def get_file_extension_for_quality(quality: str) -> str:
    """Получение расширения файла для качества"""
    extensions = {
        'flac': '.flac',
        'high': '.mp3',
        'mid': '.mp3'
    }
    return extensions.get(quality, '.mp3')

def estimate_file_size(duration_seconds: int, quality: str) -> str:
    """Оценка размера файла"""
    # Примерные битрейты в байтах в секунду
    bitrates = {
        'flac': 120000,  # ~960 kbps average
        'high': 40000,   # 320 kbps
        'mid': 16000     # 128 kbps
    }
    
    estimated_bytes = duration_seconds * bitrates.get(quality, 40000)
    
    # Форматируем размер
    if estimated_bytes > 1024 * 1024:
        return f"~{estimated_bytes / (1024 * 1024):.1f} МБ"
    else:
        return f"~{estimated_bytes / 1024:.1f} КБ"
