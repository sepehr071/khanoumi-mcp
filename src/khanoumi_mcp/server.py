"""MCP server entry point: registers every read-only Khanoumi tool."""

import logging

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, catalog, info, product  # noqa: F401  (imports register the tools)
from .registry import TOOLS

INSTRUCTIONS = """\
Unofficial, read-only access to Khanoumi (www.khanoumi.com), a large Iranian online shop for
cosmetics and makeup, skin and hair care, perfume, personal care, supplements and gold jewelry
(about 67,000 products, 3,200 brands; some items are sold by marketplace sellers). Nothing here can
log in, add to a cart, order, use a wishlist or post reviews.

Workflow:
1. Find products: kh_search (keyword, sort, price range; also returns matching category ids and
   brand slugs) or kh_find_cheapest (cheapest in-stock matches, one flat list).
2. Browse with sort / price range / filters: kh_browse with a category_id (kh_categories), brand
   slugs (kh_brands) or a campaign tag (kh_deals). Skin type, hair type, free-from, ingredient,
   color and brand filters come from kh_filters (pass its keys as facets / colors / brands).
3. One product: kh_product (every shade / size / seller with its own price, stock and max
   quantity; rating; attributes), kh_reviews (customer comments), kh_similar (alternatives or
   complementary routine products).
4. Deals: kh_deals (daily pink box with countdown, featured rows, public discount code).
   Rules and fees: kh_store_info (shipping fees, packaging, returns, payment). Guides: kh_blog_search.

Conventions: all prices are Toman. final_price is what the customer pays, price is before discount,
discount_pct is an int. A product's final_price is its cheapest shade: shades can differ, check the
chosen one in kh_product variants. Ratings are 0-5, null when nobody has rated. Products are
identified by slug ('golden-rose-sheer-bright-lipstick-112222'); the numeric id at its end also
works. Always pass the full slug from a reply: a made-up slug finds whichever product owns its
trailing number. Sponsored items are removed from lists. Persian queries match best ('رژ لب',
'کرم آبرسان'), English brand names work too.
True cost = sum(final_price x qty) + packaging_cost + shipping (kh_store_info; Tehran/Alborz courier
vs post elsewhere, 0 when an item's badges include FreeShipping) - discount code. badges are the
site's product labels (FreeShipping, Chance = pink box, New, Bestseller, Gold), shown only when set.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    "khanoumi-mcp",
    title="Khanoumi",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/sepehr071/khanoumi-mcp",
)

for fn, title in TOOLS:
    mcp.add_tool(fn, title=title, annotations=READ_ONLY)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request floods client logs
    mcp.run()


if __name__ == "__main__":
    main()
