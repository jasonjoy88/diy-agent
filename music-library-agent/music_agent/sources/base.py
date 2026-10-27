from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import DownloadResult, Track


class Source(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """该源当前是否可用（依赖就绪/配置齐全）。"""

    @abstractmethod
    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        """下载单首到 dest_dir，返回 DownloadResult（不写 manifest）。"""
