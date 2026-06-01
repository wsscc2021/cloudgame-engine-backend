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
# 부하 루프
# ---------------------------------------------------------------------------

async def progress_printer(start: float, duration: int, interval: float = 5.0):
    """테스트 진행 상황을 주기적으로 출력한다."""
    while True:
        await asyncio.sleep(interval)
        elapsed = time.perf_counter() - start
        remaining = max(0.0, duration - elapsed)
        if remaining == 0:
            break
        print(f"  경과 {elapsed:.0f}s / 남은 시간 {remaining:.0f}s ...", flush=True)


async def run(method: str, url: str, headers: dict, body,
              rps: int, duration: int, timeout: float):
    interval = 1.0 / rps
    results = []
    tasks = []

    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        wall_start = time.perf_counter()
        loop = asyncio.get_event_loop()
        loop_start = loop.time()
        end_at = loop_start + duration
        next_at = loop_start

        printer = asyncio.create_task(
            progress_printer(wall_start, duration)
        )

        while True:
            now = loop.time()
            if now >= end_at:
                break
            if now >= next_at:
                tasks.append(asyncio.create_task(
                    send_one(session, method, url, headers, body, timeout)
                ))
                next_at += interval
                # 부하가 커서 뒤처지는 경우 다음 틱으로 리셋
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

    # 상태 코드 / 오류 분포
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
        epilog="""
예시:
  # GET 요청, 초당 50건, 30초
  python load.py --url http://localhost:5000 --path /api/users \\
      --rps 50 --duration 30

  # POST 로그인, JWT 발급 부하
  python load.py --url http://localhost:5000 --path /api/auth/login \\
      --method POST --rps 20 --duration 60 --timeout 5 \\
      --body '{"username":"test","password":"Test1234!"}'

  # 인증 헤더 포함 GET
  python load.py --url http://localhost:5000 --path /api/ec2 \\
      --rps 10 --duration 10 \\
      --header "Authorization:Bearer <TOKEN>"

  # 쿼리 스트링
  python load.py --url http://localhost:5000 --path /api/users \\
      --query "role=user&page=1" --rps 30 --duration 20
        """,
    )
    p.add_argument("--url",      required=True,
                   help="베이스 URL (예: http://localhost:5000)")
    p.add_argument("--path",     default="/",
                   help="요청 경로 (기본: /)")
    p.add_argument("--method",   default="GET",
                   choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   help="HTTP 메서드 (기본: GET)")
    p.add_argument("--rps",      type=int,   default=10,
                   help="초당 요청 수 (기본: 10)")
    p.add_argument("--duration", type=int,   default=10,
                   help="테스트 시간 (초, 기본: 10)")
    p.add_argument("--timeout",  type=float, default=10.0,
                   help="요청 타임아웃 (초, 기본: 10)")
    p.add_argument("--body",     default=None,
                   help="요청 바디 JSON 문자열 (예: '{\"key\":\"value\"}')")
    p.add_argument("--query",    default="",
                   help="쿼리 스트링 (예: key=value&key2=value2)")
    p.add_argument("--header",   action="append", default=[],
                   metavar="KEY:VALUE",
                   help="추가 헤더 (반복 가능, 예: --header Authorization:Bearer TOKEN)")
    return p.parse_args()


def main():
    args = parse_args()

    # 요청 바디 파싱
    body = None
    if args.body:
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError as e:
            print(f"오류: --body 가 유효한 JSON이 아닙니다 — {e}", file=sys.stderr)
            sys.exit(1)

    # 헤더 파싱
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

    # 실행 정보 출력
    print(f"URL      : {url}")
    print(f"Method   : {args.method}")
    print(f"RPS      : {args.rps}")
    print(f"Duration : {args.duration}s")
    print(f"Timeout  : {args.timeout}s")
    if body is not None:
        print(f"Body     : {json.dumps(body, ensure_ascii=False)}")
    if headers:
        for k, v in headers.items():
            if k.lower() == "authorization":
                v = v[:12] + "..." if len(v) > 12 else v
            print(f"Header   : {k}: {v}")
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
    ))
    actual_duration = time.perf_counter() - t_start

    print_summary(results, actual_duration)


if __name__ == "__main__":
    main()
