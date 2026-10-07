# Charts 历史入口

v0.7.1 已删除新闻图表、matplotlib/mplfinance 直接依赖与 Docker 中文字体安装。新闻卡片由 deliver/cards.py 构建；见 [Pushers](pushers.md)。

盯盘的日 K 缓存与 MA/RSI/MACD 指标仍在 quote_watcher/store 与 indicators 中，不依赖新闻图表。配置见 [盯盘入门](../quote_watcher/getting_started.md)。
