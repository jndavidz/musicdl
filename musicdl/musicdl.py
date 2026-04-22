'''
Function:
    Implementation of MusicClient
Author:
    Zhenchao Jin
Modified by: Gemini (For Hi-Fi Enthusiast)
'''
import os
import sys
import copy
import click
import json_repair
from threading import Lock
from itertools import chain
from contextlib import suppress
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn, MofNCompleteColumn

if __name__ == '__main__':
    from __init__ import __version__
    from modules import BuildMusicClient, LoggerHandle, MusicClientBuilder, SongInfo, BaseMusicClient, smarttrunctable, colorize, printfullline, cursorpickintable
else:
    from .__init__ import __version__
    from .modules import BuildMusicClient, LoggerHandle, MusicClientBuilder, SongInfo, BaseMusicClient, smarttrunctable, colorize, printfullline, cursorpickintable

'''settings'''
BASIC_INFO = '''Function: Music Downloader v%s
Author: Zhenchao Jin
HIFI-MODE: Enabled (Filter < 10MB & MP3)
Music Files Save Path:
    %s (root dir is the current directory if using relative path).'''
DEFAULT_MUSIC_SOURCES = ['MiguMusicClient', 'NeteaseMusicClient', 'QQMusicClient', 'KuwoMusicClient', 'KugouMusicClient', 'QianqianMusicClient', 'GDStudioMusicClient', 'TuneHubMusicClient']

'''MusicClient'''
class MusicClient():
    LOSSLESS_QUALITY_DEFINITIONS = {'flac', 'wav', 'alac', 'ape', 'wv', 'tta', 'dsf', 'dff'}
    
    def __init__(self, music_sources: list = [], init_music_clients_cfg: dict = {}, clients_threadings: dict = {}, requests_overrides: dict = {}, search_rules: dict = {}):
        music_sources = [music_sources] if isinstance(music_sources, str) else music_sources
        music_sources, init_music_clients_cfg, clients_threadings, requests_overrides, search_rules = copy.deepcopy(music_sources), copy.deepcopy(init_music_clients_cfg), copy.deepcopy(clients_threadings), copy.deepcopy(requests_overrides), copy.deepcopy(search_rules)
        
        self.work_dirs = {}
        self.search_rules = search_rules
        self.clients_threadings = clients_threadings
        self.requests_overrides = requests_overrides
        self.music_sources = list(set(music_sources if music_sources else DEFAULT_MUSIC_SOURCES))
        self.logger_handle = LoggerHandle()
        self.music_clients: dict[str, BaseMusicClient] = dict()

        # --- 存储路径设置 ---
        save_path = '/volume1/music/download'
        if not os.path.exists(save_path):
            with suppress(Exception):
                os.makedirs(save_path, exist_ok=True)

        # --- 平台搜索数量自定义区域 ---
        source_limits = {
            'NeteaseMusicClient': 20,
            'QQMusicClient': 5,
            'MiguMusicClient': 20,
            'KuwoMusicClient': 10,
            'KugouMusicClient': 10,
            'QianqianMusicClient': 5,
            'GDStudioMusicClient': 3,
            'TuneHubMusicClient': 10,
        }

        for music_source in self.music_sources:
            if music_source not in MusicClientBuilder.REGISTERED_MODULES.keys(): continue
            
            init_music_client_cfg = {
                'search_size_per_source': source_limits.get(music_source, 5),
                'auto_set_proxies': False, 'random_update_ua': False, 'max_retries': 3, 
                'maintain_session': False, 'logger_handle': self.logger_handle, 
                'disable_print': True, 'work_dir': save_path, 'default_search_cookies': {}, 
                'default_download_cookies': {}, 'default_parse_cookies': {}, 'type': music_source, 
                'search_size_per_page': 100, 'strict_limit_search_size_per_page': True, 
                'quark_parser_config': {'cookies': 'b-user-id=f4429c9d-0be9-06b8-82ad-1def74f8934b; _UP_A4A_11_=wb9cd188279447b89c1da65450d0e3f8; __sdid=AARXlr9ltxPKevKCdBsyK3a11KwFxh7G28VEgM12liVEEPeGIpILURf7Btih15iENf9Zom/K4YW8humsKRp+stR7jl0u7+RixOosY8i3j8eYtA==; isg=BJeXkWo_sjq7djew7mxmJs9oJgvh3Gs-Q4mtKOnEDWbNGLVa8a3Xjq17ergG8EO2; tfstk=gsDIuyXxSwbQKBxpyw-Nf3m9lfw5yhJ2egZ-m0BF2JeK28g_7k5et78S143aJ9yLwPeT0uxhpUV-XGE4ryerTyr-503pxu-3pOUTYkMU2UqRXTZbqTBpxkInsqoALvR3UTw3E8L2uKJVxD2ueI3Xzm73WuqJUuUReJ2Oz6aAMKJqxDIUvno93XrqZIZzy8FLwOnTSuaRJ4FL6NUgquQL29KsXP4OpMURpRQTquCd94eJfcUg28U-yWKsXPq8ezH0PiZWOymB2ERVuqYW3Ja1eTH_XU4xAN67bAqQVrnKdTBJDkNQkDU6JDoeP5nuNYjlFriKi4qxJwLbkXunKJDyu_uSD0H0LY-l6yDstxwnHUj7JjmsFJuB46qn622tpjsRecwQRSH-7wT_kvmtnRFwHnitI2onC0SJelu4WDDLFKK0dJULClDyS9US6bHUt8bplrhE-v2nUE5rkgk53rtKo_s_iTZ_uht1Z_Va3cx9tAEDUWEgA5-6fwhu9lq_uht1ZeVLjkNwfh_pt; _UP_F7E_8D_=b0PSLv5dciMk6ehEVG9mQkO93CyQD4M6GUOU%2BWEa1%2FCQ9pt%2Flxcgspx%2F7jdZxm88%2BDZR%2F3OCavVVlSrlA%2FHE35guhUiWeFXSFrpiz7iQup7LB%2BL83Dn0lIDh36hnRcflW%2FQJYV4NNTsRzvT0bBCoNrukrbS%2BNjNcLbPeoOdhK0F%2B4CVxwd%2BA5kyclW53hcuTOm0qJXeruCsVGkVH%2BxDBFxTrs9WVELiMBAcjKqqs4gvWxrhPhsrZFoInCxl1g1C0s1YxLzJs52lWdoIk19nvWfytP81cJKxfv1GfwBTrR0bS%2FBGt91fGhZMwyZvOKbU%2F8ZkbgrGvmwxqzivluzXqQHrmHUwax9fVlczEGdRq2nJkSi56LgyDrXpsyYdGYA0F4Cj%2Fntr80vkUTca5E0LqLcBEt4UN6jDY; _UP_D_=pc; _UP_30C_6A_=sta2c6201f1ji8l9kql85eir03ig8ugo; _UP_TS_=sg1fff03673fc26db91e72b166bf2ffd147; _UP_E37_B7_=sg1fff03673fc26db91e72b166bf2ffd147; _UP_TG_=sta2c6201f1ji8l9kql85eir03ig8ugo; _UP_335_2B_=1; __pus=1eb3b1cc3511b17043141c12ea111617AAT9KoSuQZfha87NVEFyJVo3DDZVWySAc5ji3XRUBYDVhr/ihepH7xBJYUsA2V7KlV7C7ZN51udkPSUfBEiGxBC+; __kp=e5b2ee40-3d21-11f1-85f5-257d571b44f8; __kps=AAS0NX+XrbGnyrux5LIRKYjN; __ktd=yP3PLNaVCiQDNUyzuy6TCQ==; __uid=AAS0NX+XrbGnyrux5LIRKYjN; __puus=065f1b651702f50d27ea3fe3c518eeb0AASU9HC72HPY37+YERVdM7vK5rJ221YJ3T0eOCM54sw9mK2206vJ0pXemlHT+dKvUkJfdxL8Jur2JboQaGSeEP4p8vViIdViQrlPcOvqGMdI20tebH2axzpxIU1PFewNQtw7D4BBFKxQJjhsX/KkWmlMZqMIgzm2TTixguIYroJgy1VQD8SKcMVxcBgS0RqN+bYi0rlOb7aUotFZRr67WXXV'}, 'freeproxy_settings': None, 'enable_download_curl_cffi': False, 
                'enable_parse_curl_cffi': False, 'enable_search_curl_cffi': False,
            }
            
            init_music_client_cfg.update(init_music_clients_cfg.get(music_source, {}))
            self.music_clients[music_source] = BuildMusicClient(module_cfg=init_music_client_cfg)
            self.work_dirs[music_source] = init_music_client_cfg['work_dir']
            
            if music_source not in self.clients_threadings: 
                self.clients_threadings[music_source] = 5
        
    def printbasicinfo(self):
        printfullline(ch='-')
        # 这里的输出也更新一下，显示统一的下载目录
        print(BASIC_INFO % (__version__, list(self.work_dirs.values())[0] if self.work_dirs else 'N/A'))
        printfullline(ch='-')

    def printandselectsearchresults(self, search_results: dict[str, list[SongInfo]]) -> list[SongInfo]:
        print_titles = ['ID', 'Quality', 'Singers', 'Songname', 'Filesize', 'Duration', 'Album', 'Source']
        print_items, song_infos, row_ids, song_info_pointer = [], {}, [], 0
        
        for _, per_search_results in search_results.items():
            for search_result in per_search_results:
                raw_ext = str(search_result.ext).lower() if search_result.ext else 'n/a'
                filesize_mb = 0
                
                if search_result.file_size:
                    with suppress(Exception):
                        size_str = str(search_result.file_size).upper().strip()
                        if 'GB' in size_str:
                            filesize_mb = float(size_str.replace('GB', '')) * 1024
                        elif 'KB' in size_str:
                            filesize_mb = float(size_str.replace('KB', '')) / 1024
                        else:
                            filesize_mb = float(size_str.replace('MB', ''))
                
                # [Hi-Fi 过滤核心] 拦截 MP3 及 小于 10MB 的资源
                if raw_ext == 'mp3' or filesize_mb < 10.0:
                    continue

                song_info_pointer += 1
                song_infos[str(song_info_pointer)] = search_result
                row_ids.append(str(song_info_pointer))
                
                display_quality = raw_ext.upper()
                q_color = 'flac' if display_quality in self.LOSSLESS_QUALITY_DEFINITIONS else 'highlight'

                print_items.append([
                    colorize(str(song_info_pointer), 'number'), 
                    colorize(display_quality, q_color), 
                    colorize(str(search_result.singers), 'singer'), 
                    str(search_result.song_name), 
                    colorize(str(search_result.file_size), 'flac'), 
                    str(search_result.duration), 
                    str(search_result.album),
                    colorize('|'.join([str(s).upper() for s in [str(search_result.source).removesuffix('MusicClient'), search_result.root_source] if s]), 'highlight'),
                ])
        
        if not print_items:
            self.logger_handle.warning('当前范围内无符合 Hi-Fi/无损标准 的资源。')
            return []
        
        no_trunc_indices = [0, 1, 2, 4, 5, 6, 7]
        print(smarttrunctable(headers=print_titles, rows=print_items, no_trunc_cols=no_trunc_indices))
        return [song_infos[i] for i in cursorpickintable(print_titles, print_items, row_ids, no_trunc_cols=no_trunc_indices) if i in song_infos]

    def startcmdui(self):
        while True:
            self.printbasicinfo()
            keyword = self.processinputs('请输入搜索关键词: ')
            if not keyword: continue
            search_results = self.search(keyword=keyword)
            selected_song_infos = self.printandselectsearchresults(search_results=search_results)
            
            final_selected_song_infos = []
            for song_info in selected_song_infos:
                if song_info.episodes:
                    final_selected_song_infos.extend(self.printandselectsearchresults({song_info.source: song_info.episodes}))
                else:
                    final_selected_song_infos.append(song_info)
            self.download(final_selected_song_infos)

    def search(self, keyword) -> dict[str, list[SongInfo]]:
        self.logger_handle.info(f'正在多平台搜索 {colorize(keyword, "highlight")} (Hi-Fi 模式)...')
        max_workers, main_progress_lock = min(len(self.music_sources), 10), Lock()
        with Progress(TextColumn("{task.description}"), BarColumn(bar_width=None), MofNCompleteColumn(), TimeRemainingColumn(), refresh_per_second=10) as main_process_context:
            main_progress_id = main_process_context.add_task(f"多源搜索中 >>> 已完成 (0/0)", total=len(self.music_sources))
            def search_func(ms):
                try:
                    res = self.music_clients[ms].search(keyword=keyword, num_threadings=self.clients_threadings.get(ms, 5), request_overrides=self.requests_overrides.get(ms, {}), rule=self.search_rules.get(ms, {}), main_process_context=main_process_context, main_progress_id=main_progress_id, main_progress_lock=main_progress_lock)
                    with main_progress_lock: main_process_context.update(main_progress_id, advance=1)
                    return ms, res
                except Exception as err:
                    self.logger_handle.error(f'MusicClient.{ms}.search >>> (Error: {err})')
                    with main_progress_lock: main_process_context.update(main_progress_id, advance=1)
                    return ms, []
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                return dict(ex.map(search_func, self.music_sources))

    def download(self, song_infos: list[SongInfo]):
        classified = {}
        for s in song_infos: classified.setdefault(s.source, []).append(s)
        for source, infos in classified.items():
            self.music_clients[source].download(song_infos=infos, num_threadings=self.clients_threadings.get(source, 5))

    def processinputs(self, input_tip='', prefix: str = '\n'):
        with suppress(EOFError, KeyboardInterrupt):
            user_input = input(prefix + input_tip)
            if user_input.lower() == 'q': sys.exit()
            if user_input.lower() == 'r': self.startcmdui()
            return user_input
        sys.exit()

@click.command()
@click.version_option()
@click.option('-k', '--keyword', default=None, help='Search keywords.', type=str)
@click.option('-p', '--playlist-url', default=None, help='Playlist URL.', type=str)
@click.option('-m', '--music-sources', default=','.join(DEFAULT_MUSIC_SOURCES), help='Music sources.', type=str)
@click.option('-i', '--init-music-clients-cfg', default=None, help='Init config.', type=str)
@click.option('-r', '--requests-overrides', default=None, help='Requests overrides.', type=str)
@click.option('-c', '--clients-threadings', default=None, help='Threadings.', type=str)
@click.option('-s', '--search-rules', default=None, help='Search rules.', type=str)
def MusicClientCMD(keyword, playlist_url, music_sources, init_music_clients_cfg, requests_overrides, clients_threadings, search_rules):
    safe_load = lambda s: (json_repair.loads(s) or {}) if s else {}
    music_sources = [ms.strip() for ms in music_sources.split(',') if ms.strip()]
    
    client = MusicClient(
        music_sources=music_sources, 
        init_music_clients_cfg=safe_load(init_music_clients_cfg),
        clients_threadings=safe_load(clients_threadings),
        requests_overrides=safe_load(requests_overrides),
        search_rules=safe_load(search_rules)
    )
    
    if not keyword and not playlist_url:
        client.startcmdui()
    elif playlist_url:
        client.download(client.parseplaylist(playlist_url))
    else:
        results = client.search(keyword)
        selected = client.printandselectsearchresults(results)
        client.download(selected)

if __name__ == '__main__':
    MusicClientCMD()