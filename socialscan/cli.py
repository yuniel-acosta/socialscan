#! /usr/bin/env python
import argparse
import asyncio
import sys
import time
from collections import defaultdict
from operator import attrgetter

import aiohttp
import tqdm
from colorama import Fore, Style, init

from socialscan import util
from socialscan import __version__
from socialscan.platforms import Platforms

BAR_WIDTH = 50
BAR_FORMAT = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed_s:.2f}s]"
DIVIDER = "-"
DIVIDER_LENGTH = 40


async def main():
    start_time = time.time()
    init(autoreset=True)
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Command-line interface for checking email address and username usage on online platforms: " + ", ".join(p.value.__name__ for p in Platforms))
    parser.add_argument("queries", metavar="query", nargs="*",
                        help="one or more usernames/email addresses to query (email addresses are automatically be queried if they match the format)")
    parser.add_argument("--platforms", "-p", metavar="platform", nargs="*", help="list of platforms to query "
                                                                                 "(default: all platforms)")
    parser.add_argument("--input", "-i", metavar="input.txt",
                        help="file containg list of queries to execute")
    parser.add_argument("--cache-tokens", "-c", action="store_true", help="cache tokens for platforms requiring more than one HTTP request (Snapchat, GitHub, Instagram & Tumblr) "
                        " - this marginally increases runtime but halves the total number of requests")
    parser.add_argument("--available-only", "-a", action="store_true", help="only print usernames/email addresses that are available and not in use")
    parser.add_argument("--verbose", "-v", action="store_true", help="show response messages for all queries regardless of result")
    parser.add_argument("--proxy-list", metavar="proxy_list.txt", help="file containing list of proxy servers to execute queries with (useful for bypassing rate limits set by platforms)")
    parser.add_argument("--version", version=f"%(prog)s {__version__}", action="version")
    args = parser.parse_args()

    queries = args.queries
    if args.input:
        with open(args.input, "r") as f:
            for line in f:
                queries.append(line.strip("\n"))
    if not args.queries:
        raise ValueError("you must specify either at least one query or an input file")
    queries = list(dict.fromkeys(queries))
    if args.platforms:
        platforms = []
        for p in args.platforms:
            if p.upper() in Platforms.__members__:
                platforms.append(Platforms[p.upper()])
            else:
                raise ValueError(p + " is not a valid platform")
    else:
        platforms = [p for p in Platforms]
    proxy_list = []
    if args.proxy_list:
        with open(args.proxy_list, "r") as f:
            for line in f:
                proxy_list.append(line.strip("\n"))

    async with aiohttp.ClientSession() as session:
        checkers = util.init_checkers(session, proxy_list=proxy_list)
        results = defaultdict(list)
        result_count = 0
        exceptions = []

        if args.cache_tokens:
            print("Caching tokens...", end="")
            await asyncio.gather(*(util.init_prerequest(platform, checkers) for platform in platforms))
            print(end="\r")
        platform_queries = [util.query(p, query, checkers) for query in queries for p in platforms]
        for future in tqdm.tqdm(asyncio.as_completed(platform_queries), total=len(platform_queries), leave=False, ncols=BAR_WIDTH, bar_format=BAR_FORMAT):
            response = await future
            if response and (args.available_only and response.available or not args.available_only):
                results[response.query].append(response)
        for query in queries:
            responses = results[query]
            result_count += len(responses)
            header = (f"{DIVIDER * DIVIDER_LENGTH}\n"
                      f"{' ' * (DIVIDER_LENGTH // 2 - len(query) // 2) + Style.BRIGHT + query + Style.RESET_ALL}\n"
                      f"{DIVIDER * DIVIDER_LENGTH}")
            print(header)
            responses.sort(key=attrgetter('platform.name'))
            responses.sort(key=attrgetter('available', 'valid', "success"), reverse=True)
            for response in responses:
                if not response.success:
                    col = Fore.RED
                    print(col + f"{response.platform.value.__name__}: {response.message}", file=sys.stderr)
                else:
                    if response.available:
                        name_col = message_col = Fore.LIGHTGREEN_EX
                    elif not response.valid:
                        name_col = Fore.CYAN
                        message_col = Fore.WHITE
                    else:
                        name_col = Fore.YELLOW
                        message_col = Fore.WHITE
                    result_text = name_col + response.platform.value.__name__
                    if not response.valid or args.verbose:
                        result_text += f": {message_col + response.message}"
                    print(result_text)

    print(*exceptions, sep="\n", file=sys.stderr)
    print(Fore.LIGHTGREEN_EX + "Available, ", end="")
    print(Fore.YELLOW + "Taken/Reserved, ", end="")
    print(Fore.CYAN + "Invalid, ", end="")
    print(Fore.RED + "Error")
    print("Completed {} queries in {:.2f}s".format(result_count, time.time() - start_time))
