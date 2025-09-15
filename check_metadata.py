#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утилита для проверки метаданных в аудиофайлах
"""

import sys
from pathlib import Path

try:
    from mutagen import File
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    METADATA_AVAILABLE = True
except ImportError:
    print("❌ Библиотеки mutagen не установлены")
    METADATA_AVAILABLE = False
    sys.exit(1)

def check_metadata(file_path):
    """Проверка метаданных в файле"""
    if not Path(file_path).exists():
        print(f"❌ Файл не найден: {file_path}")
        return
    
    print(f"🔍 Проверка метаданных: {file_path}")
    print("=" * 60)
    
    # Загружаем файл
    audio_file = File(file_path)
    if not audio_file:
        print("❌ Не удалось загрузить файл")
        return
    
    print(f"📁 Формат файла: {audio_file.mime[0] if audio_file.mime else 'Unknown'}")
    print(f"⏱️ Длительность: {audio_file.info.length:.2f} секунд")
    print(f"🎵 Битрейт: {getattr(audio_file.info, 'bitrate', 'Unknown')} bps")
    
    # Дополнительная информация об аудио
    if hasattr(audio_file.info, 'channels'):
        channels = audio_file.info.channels
        if channels == 1:
            channel_text = "Моно"
        elif channels == 2:
            channel_text = "Стерео"
        elif channels > 2:
            channel_text = f"Многоканальный ({channels} каналов)"
        else:
            channel_text = f"{channels} каналов"
        print(f"🔊 Каналы: {channel_text}")
    
    if hasattr(audio_file.info, 'sample_rate'):
        print(f"📊 Частота дискретизации: {audio_file.info.sample_rate} Hz")
    
    if hasattr(audio_file.info, 'bits_per_sample'):
        print(f"🎚️ Битность: {audio_file.info.bits_per_sample} бит")
    
    print()
    
    # Основные теги
    print("🏷️ ОСНОВНЫЕ ТЕГИ:")
    tags_to_check = [
        ('TITLE', 'Название'),
        ('ARTIST', 'Исполнитель'), 
        ('ALBUM', 'Альбом'),
        ('ALBUMARTIST', 'Исполнитель альбома'),
        ('TRACKNUMBER', 'Номер трека'),
        ('GENRE', 'Жанр'),
        ('LYRICS', 'Текст песни')
    ]
    
    for tag_key, tag_name in tags_to_check:
        value = audio_file.get(tag_key)
        if value:
            if tag_key == 'LYRICS':
                # Показываем только первые 100 символов текста
                lyrics_preview = str(value[0])[:100] + "..." if len(str(value[0])) > 100 else str(value[0])
                print(f"  {tag_name}: {lyrics_preview}")
            else:
                print(f"  {tag_name}: {value[0] if isinstance(value, list) else value}")
        else:
            print(f"  {tag_name}: ❌ Отсутствует")
    
    print()
    
    # Проверяем обложку
    print("🖼️ ОБЛОЖКА:")
    if isinstance(audio_file, FLAC):
        pictures = audio_file.pictures
        if pictures:
            for i, picture in enumerate(pictures):
                print(f"  Обложка {i+1}: ✅ {picture.mime}, {len(picture.data)} байт")
        else:
            print("  ❌ Обложка отсутствует")
    
    elif isinstance(audio_file, MP3):
        apic_frames = [frame for frame in audio_file.tags.values() if frame.FrameID == 'APIC']
        if apic_frames:
            for i, apic in enumerate(apic_frames):
                print(f"  Обложка {i+1}: ✅ {apic.mime}, {len(apic.data)} байт")
        else:
            print("  ❌ Обложка отсутствует")

    # Дополнительно: текст в MP3 (USLT/SYLT)
    if isinstance(audio_file, MP3):
        try:
            uslt_frames = audio_file.tags.getall('USLT') if audio_file.tags else []
            sylt_frames = audio_file.tags.getall('SYLT') if audio_file.tags else []
            print()
            print("📝 ТЕКСТ (MP3):")
            if uslt_frames:
                preview = uslt_frames[0].text
                if isinstance(preview, list):
                    preview = "\n".join(preview)[:200]
                else:
                    preview = str(preview)[:200]
                print(f"  USLT: ✅, длина {len(uslt_frames)} фрейм(ов)")
                print(f"  Превью: {preview}...")
            else:
                print("  USLT: ❌ нет")
            if sylt_frames:
                # Показываем первые 3 синхро-точки
                points_shown = 0
                print(f"  SYLT: ✅, длина {len(sylt_frames)} фрейм(ов)")
                for f in sylt_frames:
                    items = getattr(f, 'text', [])
                    if isinstance(items, list) and items:
                        for item in items[:3]:
                            if isinstance(item, (list, tuple)) and len(item) == 2:
                                txt, ms = item
                                print(f"    [{ms} ms] {str(txt)[:80]}")
                                points_shown += 1
                        if points_shown:
                            break
                if points_shown == 0:
                    print("    (нет точек синхронизации для предпросмотра)")
            else:
                print("  SYLT: ❌ нет")
        except Exception as e:
            print(f"  ⚠️ Ошибка чтения текстовых фреймов: {e}")
    
    print()
    print("✅ Проверка завершена")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python check_metadata.py <путь_к_файлу>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    check_metadata(file_path)
