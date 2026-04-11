THREAD_COUNT = 8
CONCURRENT_DOWNLOAD = True
DOWNLOAD_RETRY_COUNT = 30
DECRYPTION_ENGINE = "SHAKA_PACKAGER"

SELECT_VIDEO = "best"
SELECT_AUDIO = "best"
MUX_FORMAT = "mkv"

AUTO_SUBTITLE_FIX = True
SELECT_SUBTITLE_LANGUAGES = ["fi", "suo", "swe", "en"]
SUBTITLE_FORMAT = "SRT"

SPECIAL_TRACK_PATTERNS = ["qag", "ohjelma", "program", "hoh", "cc"]

YT_DLP_OPTIONS = {
    'format': 'bestvideo+bestaudio/best',
    'merge_output_format': 'mkv',
    'force_generic_extractor': True,
    'impersonate': 'chrome',
    'socket_timeout': 60,
    'retries': 10,
    'concurrent_fragment_downloads': 8,
    'fragment_retries': 15,
    'skip_unavailable_fragments': True,
    'subtitleslangs': ['fi.*', 'suo.*', 'en.*', 'und.*'],
    'subtitlesformat': 'srt/vtt/best',
    'postprocessors': [
        {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
        {'key': 'FFmpegEmbedSubtitle'}
    ]
}

OUTPUT_FILENAME_TEMPLATE = "{title}.mkv"
TEMP_PREFIX = "fndl_"
WORK_PREFIX = "work_"