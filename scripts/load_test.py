"""Load test: how many people can one dashboard instance serve?

Streamlit runs each visitor as a websocket session that reruns the page's script on
every click. This opens N simulated sessions at once, each rendering a list of pages
over and over (exactly what a browser asks for), and reports how long a page takes to
render, how many failed, and any exception a page showed.

    # the live site, signed out (landing page only)
    python scripts/load_test.py https://<service-url> --users 20 --rounds 3

    # every page, against a local server started with DEV_AUTH_EMAIL set
    python scripts/load_test.py http://localhost:8502 --users 10 --rounds 3 \\
        --pages "" Compare Power_Rankings Trade_Analyzer Player_Rankings

Watch the instance's memory and CPU while it runs (Cloud Run metrics, or `ps` locally).
"""

import argparse
import asyncio
import statistics
import time

import websockets
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg


async def render(ws, page: str) -> tuple[float, list[str]]:
    """Ask for one page; wait for the run to finish. (seconds, exception messages)."""
    msg = BackMsg()
    msg.rerun_script.query_string = ""
    msg.rerun_script.page_name = page
    start = time.monotonic()
    await ws.send(msg.SerializeToString())
    errors, started = [], False
    while True:
        fwd = ForwardMsg()
        fwd.ParseFromString(await asyncio.wait_for(ws.recv(), timeout=180))
        kind = fwd.WhichOneof("type")
        if kind == "new_session":
            started = True
        elif kind == "delta" and fwd.delta.WhichOneof("type") == "new_element":
            element = fwd.delta.new_element
            if element.WhichOneof("type") == "exception":
                errors.append(element.exception.message[:200])
        elif kind == "page_not_found":
            errors.append(f"page not found: {page!r}")
        elif kind == "script_finished" and started:
            return time.monotonic() - start, errors


async def user(url: str, pages: list[str], rounds: int, results: list) -> None:
    ws_url = url.replace("http", "ws", 1).rstrip("/") + "/_stcore/stream"
    try:
        async with websockets.connect(ws_url, max_size=50_000_000, open_timeout=60) as ws:
            for _ in range(rounds):
                for page in pages:
                    seconds, errors = await render(ws, page)
                    results.append((page, seconds, errors))
    except Exception as error:  # a dropped or refused session counts as a failure
        results.append(("<session>", float("nan"), [f"{type(error).__name__}: {error}"]))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("url")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--pages", nargs="+", default=[""], help='url paths; "" = home')
    args = parser.parse_args()

    results: list = []
    start = time.monotonic()
    await asyncio.gather(
        *(user(args.url, args.pages, args.rounds, results) for _ in range(args.users))
    )
    wall = time.monotonic() - start

    print(f"{args.users} users x {args.rounds} rounds x {len(args.pages)} pages in {wall:.1f}s")
    for page in sorted({r[0] for r in results}):
        times = [s for p, s, _ in results if p == page and s == s]
        errors = [e for p, _, errs in results if p == page for e in errs]
        if times:
            p95 = sorted(times)[max(0, int(len(times) * 0.95) - 1)]
            median = statistics.median(times)
            print(
                f"  {page or 'home':<18} renders {len(times):>4}  median {median:5.2f}s"
                f"  p95 {p95:5.2f}s  max {max(times):5.2f}s  errors {len(errors)}"
            )
        for message in sorted(set(errors))[:5]:
            print(f"      ! {message}")


if __name__ == "__main__":
    asyncio.run(main())
