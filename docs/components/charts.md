# Charts

这一页描述 K 线图、柱状图、情绪图的生成方式，以及 TG sendPhoto inline 嵌图流程。

---

## 图表类型

| 类型 | 用途 | 实现文件 |
|---|---|---|
| K 线图（kline） | 显示个股过去 N 天的 OHLC 蜡烛图 | `charts/kline.py` |
| 柱状图（bars） | 成交量或价格对比 | `charts/bars.py` |
| 情绪图（sentiment） | 新闻情绪时序分布 | `charts/sentiment.py` |

---

## 触发时机

```yaml
# config/app.yml
charts:
  auto_on_critical: true   # is_critical=True 时自动生成 K 线图
  auto_on_earnings: true   # event_type=earnings 时自动生成
  cache_ttl_days: 30       # 缓存有效期（当前未使用 chart_cache 表）
```

!!! note "v0.1.4 移除 chart_cache 表"
    v0.1.4 删除了 `chart_cache` 表（Alembic 迁移 0003）。图表按需生成，返回 bytes，
    不再持久化到数据库。每次生成的 PNG 字节直接通过 `CommonMessage.chart_image` 传给 pusher。

---

## ChartFactory 流程

```python
class ChartFactory:
    async def render_kline(self, req: ChartRequest) -> bytes:
        # 1. 调用 data_loader(ticker, window) 获取 OHLCV DataFrame
        #    （来自 akshare，如 ak.stock_zh_a_hist 或 ak.stock_us_hist）
        # 2. 传入 kline_renderer，生成 mplfinance 图表
        # 3. 返回 PNG bytes（无文件 I/O）
        df = self._data_loader(req.ticker, req.window)
        png = self._render_kline(df, ticker=req.ticker, news_markers=None)
        return png  # bytes
```

`ChartRequest` 字段：
```python
@dataclass
class ChartRequest:
    ticker: str    # 如 "NVDA" 或 "600519"
    kind: str      # "kline" | "bars" | "sentiment"
    window: str    # "30d" | "1y" | "90d"
    params: dict   # 额外参数（如 style, volume=True）
```

---

## mplfinance 渲染

```python
# charts/kline.py 核心逻辑
import mplfinance as mpf
import io

def render_kline(df: pd.DataFrame, *, ticker: str, news_markers=None) -> bytes:
    buf = io.BytesIO()
    mpf.plot(
        df,
        type="candle",
        style="yahoo",
        title=ticker,
        savefig=dict(fname=buf, dpi=100, format="png"),
        volume=True,
    )
    return buf.getvalue()
```

返回 `bytes`，不写磁盘，直接传给 TG `sendPhoto`。

---

## TG inline 嵌图

```python
# pushers/telegram.py
if msg.chart_image:
    files = {"photo": ("chart.png", msg.chart_image, "image/png")}
    data = {"chat_id": chat_id, "caption": text_caption}
    resp = await client.post(f"{base}/sendPhoto", files=files, data=data)
```

图片作为 multipart/form-data 直接上传，无需图床。Telegram 会在消息中显示图片预览。

---

## 通过 Bot 命令生成图表

```
/chart NVDA 30d
/chart 600519 90d
```

命令处理器构建 `ChartRequest`，调用 `ChartFactory.render_kline()`，将结果 bytes 发送回请求的 chat。

---

## 飞书不显示图表

飞书推送**不包含图表**（v0.1.6 起）。原因：飞书图片上传需要自建应用 + OAuth，而飞书自建应用集成已在 v0.1.6 完全移除。

飞书卡片仍然包含摘要、badges 和链接，只是没有图片。

---

## 相关

- [Components → Pushers](pushers.md) — TG sendPhoto 集成
- [Components → Bot Commands](commands.md) — /chart 命令
- [Operations → Daily Ops](../operations/daily-ops.md) — 手动触发图表
