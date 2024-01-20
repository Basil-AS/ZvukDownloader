import json
import os
import requests
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TYER, USLT, APIC
from pathlib import Path

class SberZvukDownloader:
    def __init__(self):
        self.base_url = 'https://zvuk.com/api/tiny/'
        self.config_file = Path('./', 'config.json')
        self.config = self.load_or_create_config()
        self.headers = {'x-auth-token': self.config['token']}
        self.failed_tracks = []

    def load_or_create_config(self):
        if not self.config_file.exists():
            return self.first_start_config()
        with open(self.config_file, 'r', encoding='utf-8') as file:
            return json.load(file)

    def first_start_config(self):
        print('Первый запуск. Пожалуйста, настройте ваш скрипт.')
        config = {}
        config['token'] = input('Введите ваш токен: ')
        config['format'] = input('Выберите формат аудио (1 - FLAC, 2 - MP3): ')
        config['lyrics'] = input('Скачивать тексты песен? (1 - Да, 2 - Нет): ') == '1'
        config['download_path'] = input('Введите путь для сохранения музыки [./music]: ') or './music'
        config['fallback_to_lower_quality'] = input('Скачивать низкое качество, если FLAC недоступен? (1 - Да, 2 - Нет): ') == '1'
        config['cover_resolution'] = input('Выберите разрешение обложки (1 - максимальное, 2 - стандартное(500x500)): ') == '1'

        with open(self.config_file, 'w', encoding='utf-8') as file:
            json.dump(config, file, indent=4)

        return config

    def get_track_info(self, track_id):
        try:
            url = self.base_url + 'tracks'
            params = {'ids': track_id}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()['result']['tracks'][str(track_id)]
        except Exception as e:
            print(f"Ошибка при получении информации о треке: {e}")
            self.failed_tracks.append(track_id)
            return None

    def download_track(self, track_info):
        if not track_info:
            return

        track_id = track_info['id']
        preferred_format = 'flac' if self.config.get('format', '1') == '1' else 'high'
        available_format = 'flac' if track_info.get('has_flac', False) else 'high'

        if preferred_format != available_format and not self.config['fallback_to_lower_quality']:
            print(f"\033[93mFLAC недоступен для трека {track_info['title']}, и не выбрано скачивание низкого качества.\033[0m")
            self.failed_tracks.append(track_id)
            return

        try:
            stream_url = self.base_url + 'track/stream'
            params = {'id': track_id, 'quality': available_format}
            response = requests.get(stream_url, headers=self.headers, params=params)
            response.raise_for_status()
            track_url = response.json()['result']['stream']

            file_extension = 'flac' if available_format == 'flac' else 'mp3'
            file_name = f"{track_info['artist_names'][0]} - {track_info['title']}.{file_extension}"
            download_path = Path(self.config.get('download_path', './music'))
            download_path.mkdir(parents=True, exist_ok=True)
            file_path = download_path / file_name.replace('/', '_')

            print(f"\033[96mСкачивается трек: {file_name} в формате {available_format.upper()} {'с текстом' if self.config['lyrics'] else ''}\033[0m")

            with requests.get(track_url, stream=True) as r:
                r.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            self.add_metadata(file_path, track_info, available_format)

            if self.config['lyrics']:
                self.add_lyrics(file_path, track_id)

            print(f"\033[92mТрек успешно скачан: {file_name}\033[0m")
        except Exception as e:
            print(f"\033[91mОшибка при загрузке трека {track_info['title']}: {e}\033[0m")
            self.failed_tracks.append(track_id)

    def add_metadata(self, file_path, track_info, format):
        try:
            cover_size = 'max' if self.config['cover_resolution'] == '1' else '500x500'
            cover_url = track_info['image']['src'].replace(r"&size={size}&ext=jpg", f"&size={cover_size}&ext=jpg")
            cover_data = requests.get(cover_url).content

            if format == 'flac':
                audio = FLAC(file_path)
                audio['ARTIST'] = track_info['artist_names']
                audio['TITLE'] = track_info['title']
                audio['ALBUM'] = track_info.get('release_title', 'Неизвестный альбом')
                audio['TRACKNUMBER'] = str(track_info.get('position', 0))
                audio['DATE'] = track_info.get('release_date', 'Неизвестная дата')[:4]

                picture = Picture()
                picture.data = cover_data
                picture.type = 3  # front cover
                picture.mime = 'image/jpeg'
                audio.add_picture(picture)

                audio.save()
            else:
                audio = MP3(file_path, ID3=ID3)
                audio.tags.add(TPE1(encoding=3, text=track_info['artist_names']))
                audio.tags.add(TIT2(encoding=3, text=track_info['title']))
                audio.tags.add(TALB(encoding=3, text=track_info.get('release_title', 'Неизвестный альбом')))
                audio.tags.add(TRCK(encoding=3, text=str(track_info.get('position', 0))))
                audio.tags.add(TYER(encoding=3, text=track_info.get('release_date', 'Неизвестная дата')[:4]))
                audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=cover_data))
                audio.save()
        except Exception as e:
            print(f"\033[91mОшибка при добавлении метаданных: {e}\033[0m")
            self.failed_tracks.append(track_info['id'])

    def add_lyrics(self, file_path, track_id):
        try:
            lyrics_url = self.base_url + 'musixmatch/lyrics'
            params = {'track_id': track_id}
            response = requests.get(lyrics_url, headers=self.headers, params=params)
            if response.status_code == 200:
                lyrics = response.json()['result']['lyrics']
                if self.config['format'] == '1':
                    audio = FLAC(file_path)
                    audio['LYRICS'] = lyrics
                    audio.save()
                else:
                    audio = MP3(file_path, ID3=ID3)
                    audio.tags.add(USLT(encoding=3, text=lyrics))
                    audio.save()
        except Exception as e:
            print(f"\033[91mОшибка при добавлении текста песни: {e}\033[0m")

    def process_album_or_playlist(self, link):
        try:
            link_type = 'releases' if 'release' in link else 'playlists'
            item_id = link.split('/')[-1]
            url = self.base_url + link_type
            params = {'ids': item_id}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            track_ids = response.json()['result'][link_type][item_id]['track_ids']
            for track_id in track_ids:
                track_info = self.get_track_info(track_id)
                self.download_track(track_info)
        except Exception as e:
            print(f"\033[91mОшибка при обработке {link_type[:-1]} {link}: {e}\033[0m")
            self.failed_tracks.append(item_id)

    def process_links(self, links):
        for link in links:
            if 'track' in link:
                track_id = link.split('/')[-1]
                track_info = self.get_track_info(track_id)
                self.download_track(track_info)
            elif 'release' in link or 'playlist' in link:
                self.process_album_or_playlist(link)

        if self.failed_tracks:
            print("\033[91mНе удалось скачать следующие треки/альбомы:\033[0m")
            for track_id in self.failed_tracks:
                print(f"- {track_id}")
        else:
            print("\033[92mВсе треки успешно скачаны!\033[0m")

if __name__ == '__main__':
    downloader = SberZvukDownloader()

    links_input = input('Введите ссылки через запятую: ')
    links = links_input.split(',')
    downloader.process_links(links)

    if downloader.failed_tracks:
        print("\033[91mНе удалось скачать следующие треки/альбомы:\033[0m")
        for track_id in downloader.failed_tracks:
            print(f"- {track_id}")
    else:
        print("\033[92mВсе треки успешно скачаны!\033[0m")