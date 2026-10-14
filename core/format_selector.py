"""MP4-only format selection for yt-dlp.

The selector is an ordered list of alternatives separated by ``/``; yt-dlp
uses the first one that matches. Every alternative yields **video with
audio**: either a video-only stream merged with an audio stream, or a
progressive stream that already contains both. Audio-only results are
impossible by construction.

Priority (``H`` = selected maximum height):

1. MP4 video ≤ H + M4A (AAC) audio      -> lossless remux into MP4
2. MP4 video ≤ H + any audio            -> merged into MP4
3. progressive MP4 ≤ H                  -> already MP4
4. any video ≤ H + audio                -> merged into an MP4 container
5. any progressive stream ≤ H           -> converted to MP4 afterwards
6. lowest available video + audio       -> only when nothing ≤ H exists

Because each alternative takes the *best* stream at or below ``H``, a
missing quality automatically falls back to the next closest lower one.
"""

from __future__ import annotations

from config.constants import QUALITY_OPTIONS


def quality_to_height(label: str) -> int | None:
    """Translate a quality label from the UI into a maximum height."""
    for option_label, height in QUALITY_OPTIONS:
        if option_label == label:
            return height
    return None


def build_format_selector(max_height: int | None) -> str:
    """Build the yt-dlp ``format`` string for a maximum height."""
    h = f"[height<={max_height}]" if max_height else ""
    alternatives = (
        f"bv{h}[ext=mp4]+ba[ext=m4a]",
        f"bv{h}[ext=mp4]+ba",
        f"b{h}[ext=mp4][acodec!=none][vcodec!=none]",
        f"bv{h}+ba[ext=m4a]",
        f"bv{h}+ba",
        f"b{h}[acodec!=none][vcodec!=none]",
        "wv+ba",
        "w[acodec!=none][vcodec!=none]",
    )
    return "/".join(alternatives)


def build_format_sort(max_height: int | None, prefer_h264: bool = True) -> list[str]:
    """Sort order used to rank formats that pass the selector filters.

    Resolution always dominates, so H.264 is only preferred among formats
    of the same height (4K, which YouTube only offers as AV1/VP9, still wins).
    """
    order = [f"res:{max_height}" if max_height else "res", "fps"]
    if prefer_h264:
        order.append("vcodec:h264")
    order += ["acodec:aac", "ext:mp4:m4a"]
    return order
