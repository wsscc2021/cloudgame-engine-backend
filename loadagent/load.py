#!/usr/bin/env python3
"""HTTP 부하 테스트 클라이언트"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from urllib.parse import urlparse, urlunparse

import aiohttp


# ---------------------------------------------------------------------------
# HTTP 요청
# ---------------------------------------------------------------------------

async def send_one(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict,
    body,
    timeout: float,
):
    t0 = time.perf_counter()
    try:
        kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=timeout)}
        if body is not None:
            kwargs["json"] = body
        async with session.request(method, url, **kwargs) as resp:
            await resp.read()
            return resp.status, time.perf_counter() - t0, None
    except asyncio.TimeoutError:
        return None, time.perf_counter() - t0, "timeout"
    except Exception as e:
        return None, time.perf_counter() - t0, type(e).__name__


# ---------------------------------------------------------------------------
# 이벤트 로그 드레인 (1초마다 백엔드로 전송)
# ---------------------------------------------------------------------------

async def _drain_loop(
    queue: asyncio.Queue,
    stop_evt: asyncio.Event,
    log_url: str,
    log_token: str,
):
    async with aiohttp.ClientSession() as log_sess:
        while not stop_evt.is_set():
            await asyncio.sleep(1)
            await _flush(queue, log_sess, log_url, log_token)
        await _flush(queue, log_sess, log_url, log_token)  # 종료 후 잔여 전송


async def _flush(
    queue: asyncio.Queue,
    log_sess: aiohttp.ClientSession,
    log_url: str,
    log_token: str,
):
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    if not events:
        return
    try:
        await log_sess.post(
            log_url,
            json={"token": log_token, "events": events},
            timeout=aiohttp.ClientTimeout(total=3),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 부하 루프
# ---------------------------------------------------------------------------

async def progress_printer(start: float, duration: int, interval: float = 5.0):
    while True:
        await asyncio.sleep(interval)
        elapsed   = time.perf_counter() - start
        remaining = max(0.0, duration - elapsed)
        if remaining == 0:
            break
        print(f"  경과 {elapsed:.0f}s / 남은 시간 {remaining:.0f}s ...", flush=True)


async def run(
    method: str,
    url: str,
    headers: dict,
    body,
    rps: int,
    duration: int,
    timeout: float,
    log_url: str = None,
    log_token: str = "",
):
    interval    = 1.0 / rps
    results     = []
    tasks       = []
    event_queue = asyncio.Queue() if log_url else None
    stop_evt    = asyncio.Event()

    # 이벤트를 큐에 쌓는 래퍼
    async def _tracked(sess, m, u, h, b, to):
        t_wall = time.time()
        result = await send_one(sess, m, u, h, b, to)
        if event_queue is not None:
            s, l, e = result
            await event_queue.put({
                "t": round(t_wall, 3),
                "s": s,
                "l": round(l * 1000, 2),
                "e": e,
            })
        return result

    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        wall_start = time.perf_counter()
        loop       = asyncio.get_event_loop()
        loop_start = loop.time()
        end_at     = loop_start + duration
        next_at    = loop_start

        printer    = asyncio.create_task(progress_printer(wall_start, duration))
        drain_task = asyncio.create_task(
            _drain_loop(event_queue, stop_evt, log_url, log_token)
        ) if event_queue is not None else None

        while True:
            now = loop.time()
            if now >= end_at:
                break
            if now >= next_at:
                tasks.append(asyncio.create_task(
                    _tracked(session, method, url, headers, body, timeout)
                ))
                next_at += interval
                if next_at < now:
                    next_at = now + interval
            else:
                sleep_for = min(next_at - now, end_at - now)
                await asyncio.sleep(sleep_for)

        printer.cancel()

        if tasks:
            raw = await asyncio.gather(*tasks, return_exceptions=True)
            for r in raw:
                if isinstance(r, Exception):
                    results.append((None, 0.0, str(r)))
                else:
                    results.append(r)

    # 드레인 종료
    stop_evt.set()
    if drain_task:
        await drain_task

    return results


# ---------------------------------------------------------------------------
# 결과 출력
# ---------------------------------------------------------------------------

def print_summary(results: list, actual_duration: float):
    total = len(results)
    if total == 0:
        print("\n전송된 요청이 없습니다.")
        return

    ok_count  = sum(1 for s, _, _ in results if s is not None and 200 <= s < 300)
    err_count = total - ok_count
    latencies = sorted(l for _, l, _ in results)

    def pct(p: float) -> float:
        idx = min(int(len(latencies) * p / 100), len(latencies) - 1)
        return latencies[idx]

    status_dist: dict[int, int] = {}
    error_dist:  dict[str, int] = {}
    for s, _, e in results:
        if s is not None:
            status_dist[s] = status_dist.get(s, 0) + 1
        else:
            error_dist[e or "unknown"] = error_dist.get(e or "unknown", 0) + 1

    w = 50
    print("\n" + "=" * w)
    print("  부하 테스트 결과")
    print("=" * w)
    print(f"  총 요청 수     : {total:>8}")
    print(f"  성공 (2xx)     : {ok_count:>8}")
    print(f"  실패           : {err_count:>8}")
    print(f"  실제 RPS       : {total / actual_duration:>8.1f}")
    print("-" * w)
    print("  응답 시간 (ms)")
    print(f"    최소         : {min(latencies)*1000:>8.1f}")
    print(f"    평균         : {statistics.mean(latencies)*1000:>8.1f}")
    print(f"    p50          : {pct(50)*1000:>8.1f}")
    print(f"    p90          : {pct(90)*1000:>8.1f}")
    print(f"    p95          : {pct(95)*1000:>8.1f}")
    print(f"    p99          : {pct(99)*1000:>8.1f}")
    print(f"    최대         : {max(latencies)*1000:>8.1f}")

    if status_dist or error_dist:
        print("-" * w)
        print("  응답 분포")
        for code, cnt in sorted(status_dist.items()):
            print(f"    HTTP {code}       : {cnt:>8}")
        for err, cnt in sorted(error_dist.items()):
            print(f"    오류 ({err:<10}): {cnt:>8}")

    print("=" * w)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_url(base: str, path: str, query: str) -> str:
    parsed = urlparse(base.rstrip("/") + "/" + path.lstrip("/"))
    qs = (parsed.query + "&" + query).lstrip("&") if query else parsed.query
    return urlunparse(parsed._replace(query=qs))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HTTP 부하 테스트 클라이언트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url",       required=True)
    p.add_argument("--path",      default="/")
    p.add_argument("--method",    default="GET",
                   choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    p.add_argument("--rps",       type=int,   default=10)
    p.add_argument("--duration",  type=int,   default=10)
    p.add_argument("--timeout",   type=float, default=10.0)
    p.add_argument("--body",      default=None)
    p.add_argument("--query",     default="")
    p.add_argument("--header",    action="append", default=[], metavar="KEY:VALUE")
    p.add_argument("--log-url",   default=None,  help="이벤트 로그를 전송할 백엔드 URL")
    p.add_argument("--log-token", default="",    help="백엔드 인증 토큰")
    return p.parse_args()


def main():
    args = parse_args()

    body = None
    if args.body:
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError as e:
            print(f"오류: --body 가 유효한 JSON이 아닙니다 — {e}", file=sys.stderr)
            sys.exit(1)

    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for h in args.header:
        if ":" not in h:
            print(f"오류: 헤더 형식 오류 (KEY:VALUE 필요) — '{h}'", file=sys.stderr)
            sys.exit(1)
        k, v = h.split(":", 1)
        headers[k.strip()] = v.strip()

    url = build_url(args.url, args.path, args.query)

    print(f"URL      : {url}")
    print(f"Method   : {args.method}")
    print(f"RPS      : {args.rps}")
    print(f"Duration : {args.duration}s")
    print(f"Timeout  : {args.timeout}s")
    if body is not None:
        print(f"Body     : {json.dumps(body, ensure_ascii=False)}")
    print("\n테스트 시작...\n")

    t_start = time.perf_counter()
    results = asyncio.run(run(
        method=args.method.upper(),
        url=url,
        headers=headers,
        body=body,
        rps=args.rps,
        duration=args.duration,
        timeout=args.timeout,
        log_url=args.log_url,
        log_token=args.log_token,
    ))
    actual_duration = time.perf_counter() - t_start

    print_summary(results, actual_duration)


if __name__ == "__main__":
    main()
