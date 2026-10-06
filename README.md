<!-- mcp-name: io.github.sepehr071/khanoumi-mcp -->

<div align="center">

<img src="https://raw.githubusercontent.com/sepehr071/khanoumi-mcp/main/.github/banner.png" alt="khanoumi-mcp: let your AI agent find the cheapest cosmetics and skin care on Khanoumi" width="100%">

# 💄 khanoumi-mcp

**Let your AI agent shop for cosmetics and skin care on Khanoumi.**<br>
Search makeup, skin and hair care and perfume, compare real prices and shades, filter by skin type,<br>
read reviews and catch today's pink-box deals, all from Claude, Cursor or Copilot.

[![PyPI](https://img.shields.io/pypi/v/khanoumi-mcp?color=2563eb)](https://pypi.org/project/khanoumi-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/khanoumi-mcp)](https://pypi.org/project/khanoumi-mcp/)
[![CI](https://github.com/sepehr071/khanoumi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/khanoumi-mcp/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-io.github.sepehr071%2Fkhanoumi--mcp-7c3aed)](https://registry.modelcontextprotocol.io/?q=khanoumi-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/khanoumi-mcp/blob/main/LICENSE)

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=khanoumi&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJraGFub3VtaS1tY3AiXX0=)
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_khanoumi--mcp-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=khanoumi&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22khanoumi-mcp%22%5D%7D)

[Quick start](#quick-start) · [What it can do](#what-it-can-do) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## Why

Khanoumi lists about 67,000 beauty products from 3,200 brands. A search for "sunscreen" mixes sponsored
items, out-of-stock products and shades with different prices, and the fees only show up at checkout.
Finding *the cheapest one you can actually order, and what it costs delivered*, means a lot of clicking.
An agent with `khanoumi-mcp` does that in seconds:

> **You:** Cheapest Cinere sunscreen I can order now, delivered in Tehran?
>
> **Agent:** *calls* `kh_find_cheapest(query="ضد آفتاب سینره")` → `kh_store_info(topic="delivery")`
>
> | Total | Product | Price |
> |---:|---|---:|
> | **924,000** | کرم ضد آفتاب بی رنگ با SPF45 مناسب آقایان | 785,000 (25% off) |
> | **926,500** | کرم ضد آفتاب بی رنگ Oil Free SPF50 مناسب پوست چرب | 787,500 (25% off) |
> | **964,000** | ضد آفتاب رنگی +SPF60 مات کننده پوست چرب (2 shades) | 825,000 (25% off) |
>
> Totals include 20,000 packaging and the 119,000 Tehran courier fee. The SPF45 for men is cheapest; if you
> have oily skin the Oil Free SPF50 costs only 2,500 more. Want me to check which tinted shade is in stock with `kh_product`?

<sub>Real tool output from 2026-10-06; prices change all the time. Prices are in Toman.</sub>

## What it can do

- 🔎 **Search** products by name in Persian or English, with price, discount and stock, sponsored items removed
- 💸 **Find the cheapest** in-stock match for a keyword, optionally inside one category
- 🗂️ **Browse** any category, brand or campaign sorted by price, popularity or date, with price range and filters
- 🧴 **Filter** by skin type, hair type, free-from (paraben, sulfate), key ingredients, color and brand
- 💋 **Read** full product details: every shade or size with its own price and stock, sellers, gold price breakdown
- 💬 **Check reviews**, similar products and the routine products the shop pairs with an item
- ⚡ **Catch deals**: the daily pink box with its countdown, featured rows and the current public discount code
- 🚚 **Know the fees**: packaging, shipping, returns and payment rules from the official FAQ, plus beauty guides from the blog
- 🔒 **Read-only by design**: no login, no cart, no orders, no reviews posted

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add khanoumi -- uvx khanoumi-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "khanoumi": { "command": "uvx", "args": ["khanoumi-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Cursor</b></summary>

Click **Install in Cursor** above, or add the Claude Desktop block to `~/.cursor/mcp.json`.
</details>

<details>
<summary><b>VS Code (Copilot agent mode)</b></summary>

Click **Install in VS Code** above, or add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "khanoumi": { "type": "stdio", "command": "uvx", "args": ["khanoumi-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Anything else</b></summary>

It's a standard stdio MCP server: run `uvx khanoumi-mcp`, or `pip install khanoumi-mcp` and run `khanoumi-mcp`.
</details>

Then just ask:

- "Cheapest moisturizer for oily skin under 500,000 Toman, and what do buyers say about it?"
- "Which shades of the Golden Rose Sheer Bright lipstick are in stock, and do they cost the same?"
- "What's in today's pink box, and is there a discount code?"
- <span dir="rtl">ارزان&zwnj;ترین شامپوی ضد ریزش سریتا با ارسال به تهران چند درمیاد؟</span>

## How it works

```text
  AI agent  (Claude, Cursor, Copilot, ...)
      │
      │  MCP over stdio
      ▼
  khanoumi-mcp  (runs on your machine)
      │
      │  HTTPS
      └──────▶  www.khanoumi.com   JSON API, FAQ page, blog
```

`khanoumi-mcp` runs locally and calls the same public endpoints the khanoumi.com website uses.
There's no hosted server in between, no API key, and nothing about you is sent anywhere else.

## Tools

<details open>
<summary><b>🔎 Find products</b> (7)</summary>

| Tool | What it does |
|---|---|
| `kh_search` | Search by keyword: price, discount, stock, plus matching categories and brands |
| `kh_find_cheapest` | Cheapest in-stock matches for a keyword, one flat list sorted by payable price |
| `kh_browse` | A category, brand or campaign tag sorted by price / popularity / date, with price range and filters |
| `kh_filters` | Sub-categories, brands, colors, skin / hair type and ingredient filters, price range and stock counts of a listing |
| `kh_categories` | Category tree with ids, paths and product counts |
| `kh_brands` | Find brands and their slugs |
| `kh_deals` | Today's pink box and featured deals, biggest discount first, with the countdown and the public discount code |
</details>

<details open>
<summary><b>💋 One product</b> (3)</summary>

| Tool | What it does |
|---|---|
| `kh_product` | Price, discount, every shade / size / seller with its own price and stock, rating, attributes, description |
| `kh_reviews` | Customer comments, newest first, with verified-buyer flag and photos |
| `kh_similar` | Alternatives to a product, or the products the shop pairs with it |
</details>

<details open>
<summary><b>📝 Store and blog</b> (2)</summary>

| Tool | What it does |
|---|---|
| `kh_store_info` | Packaging cost, shipping fees and times, returns, payment and guarantee rules from the FAQ |
| `kh_blog_search` | Buying guides, routines and ingredient explainers from the Khanoumi magazine |
</details>

All 12 tools are annotated `readOnlyHint: true` and return compact structured JSON, so they don't flood the agent's context.

## Good to know

- **Prices are in Toman.** `final_price` is what you pay, `price` is before discount, `discount_pct` is a whole percent.
- **Shades can cost different amounts.** A product's `final_price` is its cheapest shade or size; `kh_product` lists each variant with its own price, stock (`in_stock`) and maximum quantity per order.
- **Order cost**: items + 20,000 packaging + shipping (119,000 Tehran / Alborz courier, 113,000 post to other provinces on 2026-10-06; free for items tagged "ارسال رایگان", shown as `FreeShipping` in a product's `badges`). `kh_store_info` reads the current fees. The exact quote per address needs a login, so it isn't available here.
- **Sponsored items are removed** from search and listings, and `total` counts only real matches. Pages follow on from each other without gaps or repeats, which the site's own pager doesn't manage when ads are on the page.
- **Ratings are 0–5**, `null` when nobody has rated the product yet. Review comments carry no stars.
- **Persian queries match best** (`کرم آبرسان`, `رژ لب`), but English brand names work too (`cerave`, `golden rose`).

## FAQ

<details>
<summary><b>Can it place an order for me?</b></summary>

No, and that's deliberate. It has no login and never touches the cart, order, payment, wishlist, notify-me or review endpoints.
The agent finds the best option; you buy it on khanoumi.com.
</details>

<details>
<summary><b>Why does <code>kh_find_cheapest</code> skip some items?</b></summary>

It keeps only items you can order now whose Persian or English title or brand contains every word of your query
(`match_all_words: false` turns that off). It scans the first 300 results, cheapest first; `complete: false` in the reply
means more matches lie past that, so raise `scan` (up to 900) or narrow with `category_id`. `kh_search` shows everything.
</details>

<details>
<summary><b>How do I filter by skin type or ingredient?</b></summary>

Call `kh_filters` for the category (for example `category_id: 145`, moisturizers) and pass the keys you want to
`kh_browse`, e.g. `facets: ["facetKey.skin-type:oily"]`. Several facets must all match; several brands or colors match any.
</details>

<details>
<summary><b>I get "Could not reach khanoumi.com"</b></summary>

The server retries a dropped connection once. If it still fails, check your internet connection. System proxy
variables are ignored on purpose; set `KHANOUMI_MCP_PROXY` if you need a proxy.
</details>

<details>
<summary><b>Claude Desktop says <code>uvx</code> is not found</b></summary>

Use the full path to `uvx` (`where uvx` on Windows, `which uvx` on macOS/Linux) as `command`.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx khanoumi-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KHANOUMI_MCP_PROXY` | unset | HTTP proxy for every request, e.g. `http://user:pass@host:port` |

## فارسی

<div dir="rtl">

**khanoumi-mcp** به دستیار هوش مصنوعی شما (Claude، Cursor، Copilot و ...) اجازه می&zwnj;دهد در خانومی جستجو کند،
ارزان&zwnj;ترین محصول موجود را پیدا کند، رنگ&zwnj;ها و قیمت هر رنگ را ببیند، بر اساس نوع پوست و مو فیلتر کند،
نظرات خریداران را بخواند و تخفیف&zwnj;های جعبه صورتی و کد تخفیف روز را پیدا کند.

- فقط خواندنی است: وارد حساب نمی&zwnj;شود، سبد خرید نمی&zwnj;سازد، سفارش ثبت نمی&zwnj;کند و نظر نمی&zwnj;فرستد.
- قیمت&zwnj;ها به تومان است و محصولات تبلیغاتی (اسپانسری) از نتایج حذف می&zwnj;شوند.
- روی سیستم خود شما اجرا می&zwnj;شود و به هیچ سرور واسطی داده نمی&zwnj;فرستد.

**نصب در Claude Code:**

</div>

```bash
claude mcp add khanoumi -- uvx khanoumi-mcp
```

<div dir="rtl">

بعد بپرسید: «ارزان&zwnj;ترین کرم آبرسان مناسب پوست چرب زیر ۵۰۰ هزار تومان کدام است و خریداران درباره&zwnj;اش چه می&zwnj;گویند؟»

</div>

## Development

```bash
git clone https://github.com/sepehr071/khanoumi-mcp && cd khanoumi-mcp
uv sync
uv run pytest            # offline, against recorded responses
uv run pytest -m live    # real khanoumi.com
uv run ruff check .
```

Tools live in `src/khanoumi_mcp/catalog.py`, `product.py` and `info.py`; each is a typed async function with a
docstring that tells the agent when to use it. Issues and PRs are welcome, especially new tools and fixes for site changes.

Releases: bump the version in `pyproject.toml` and `server.json`, then push a `v*` tag. GitHub Actions tests,
publishes to PyPI and the [MCP Registry](https://registry.modelcontextprotocol.io), and creates the GitHub Release.

## Disclaimer

Unofficial and not affiliated with or endorsed by Khanoumi. It uses the public endpoints of the khanoumi.com
website, which can change without notice. Please keep request rates reasonable.

## License

[MIT](https://github.com/sepehr071/khanoumi-mcp/blob/main/LICENSE)
