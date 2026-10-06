"""One product: details with every shade / seller, reviews, similar and complementary products."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .catalog import _badges, _item, _text
from .http import BASE, ApiError, api
from .registry import tool

ProductRef = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9-]{0,200}\d$",
        description="Product slug from kh_search / kh_browse (e.g. 'golden-rose-sheer-bright-lipstick-112222') "
        "or the numeric product id (e.g. '112222').",
    ),
]


@tool("Product details")
async def kh_product(product: ProductRef) -> dict[str, Any]:
    """Get one product's full record: price and discount (Toman), every shade / size / seller variant with its
    own price, stock and max quantity, rating, brand, category path, attributes (skin / hair type, key
    ingredients, texture, country) and the description.

    Use after kh_search / kh_browse when the user picks a product, or to check that the shade they
    want is in stock and what it costs. Reviews: kh_reviews. Alternatives: kh_similar.
    Fees for the order total: kh_store_info.
    """
    slug = await _slug(product)
    p = await api(f"/api/ntl/v1/products/slug/{slug}")
    if not p:
        raise ApiError(f"No product '{product}' on khanoumi.com. Get slugs from kh_search.")
    final, price, pct = p.get("salesPrice"), p.get("basePrice"), int(p.get("discountPercent") or 0)
    brand = p.get("brand") or {}
    return {
        "id": int(p["id"]),
        "slug": p.get("slug"),
        "title": (p.get("nameFa") or "").strip(),
        "title_en": p.get("nameEn"),
        "brand": brand.get("nameFa") or brand.get("nameEn"),
        "brand_slug": brand.get("slug"),
        "authenticity": brand.get("consideration"),
        "final_price": final or None,
        "price": (final if not pct else price) or None,
        "discount_pct": pct,
        "in_stock": bool(p.get("isSalable")),
        "discontinued": bool(p.get("isDiscontinued")),
        "badges": _badges(p.get("flags")),
        "rating": p.get("rate") if p.get("ratesCount") else None,
        "rating_count": p.get("ratesCount") or 0,
        "comment_count": p.get("commentsCount") or 0,
        "categories": [{"id": int(c["id"]), "title": c.get("nameFa")} for c in p.get("breadcrumb") or []],
        "variants": [_variant(v) for v in p.get("variants") or []],
        "attributes": {
            a.get("nameFa"): [v.get("nameFa") for v in a.get("values") or []] for a in p.get("attributes") or []
        },
        "description": _clip(_text(p.get("descriptionHtmlFa")), 1500),
        "how_to_use": _clip(_text(p.get("howToUseHtml")), 800),
        "image": p.get("mainImageUrl"),
        "url": f"{BASE}/products/{p.get('slug')}",
    }


@tool("Product reviews")
async def kh_reviews(
    product: ProductRef,
    with_photos: Annotated[bool, Field(description="Only reviews that include customer photos.")] = False,
    page: Annotated[int, Field(ge=1, le=500, description="Page number, from 1, newest first.")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="Reviews per page.")] = 20,
) -> dict[str, Any]:
    """Read customer comments on a product, newest first, with a verified-buyer flag and photos.

    Use as a quality check before recommending a product. Comments carry no star rating: the
    product's average rating and rating count are in kh_product.
    """
    product_id = re.search(r"(\d+)$", product).group(1)  # type: ignore[union-attr]  # the pattern ends in a digit
    data = await api(
        f"/api/cml/v1/products/id/{product_id}/comments",
        {"page_number": page, "page_size": limit, "has_image": "true" if with_photos else None},
    )
    if not data.get("totalCount"):
        await _slug(product_id)  # an unknown id also has no comments: raise not-found instead
    return {
        "total": int(data.get("totalCount") or 0),
        "page": page,
        "reviews": [
            {
                "author": (c.get("userName") or "").strip() or None,
                "buyer": bool(c.get("isBuyer")),
                "date": (c.get("createdAt") or "")[:10] or None,
                "text": (c.get("description") or "").strip(),
                "likes": c.get("likeCount") or 0,
                **({"photos": c["imageUrls"]} if c.get("imageUrls") else {}),
            }
            for c in data.get("items") or []
        ],
    }


@tool("Similar and complementary products")
async def kh_similar(
    product: ProductRef,
    kind: Annotated[
        Literal["similar", "complementary"],
        Field(
            description="similar = alternatives to this product; complementary = products the shop pairs with it (routine)."
        ),
    ] = "similar",
    in_stock_only: Annotated[bool, Field(description="Only products that can be ordered now.")] = False,
) -> dict[str, Any]:
    """List alternatives to a product (about 20) or the products the shop pairs with it, with prices and stock.

    Use when a product is out of stock or too expensive, or to build a routine / bundle around it.
    Complementary lists are empty for most products.
    """
    slug = await _slug(product)
    data = await api(f"/api/ntl/v1/products/slug/{slug}/{kind}")
    if not data and not product.isdigit():  # an unknown slug also lists nothing: raise not-found instead
        await _slug(re.search(r"(\d+)$", slug).group(1))  # type: ignore[union-attr]
    items = [_item(p) for p in data or [] if not p.get("ad")]
    if in_stock_only:
        items = [p for p in items if p["in_stock"]]
    return {"count": len(items), "products": items}


async def _slug(ref: str) -> str:
    """A bare id is turned into the slug: the slug endpoints look up by the trailing id of a full slug only."""
    if not ref.isdigit():
        return ref
    data = await api(f"/api/ntl/v1/products/id/{ref}")
    if not data or not data.get("slug"):
        raise ApiError(f"No product with id {ref} on khanoumi.com. Get products from kh_search.")
    return data["slug"]


def _variant(v: dict[str, Any]) -> dict[str, Any]:
    """One buyable offer: a shade / size, or one marketplace seller's offer."""
    final, price, pct = v.get("salesPrice"), v.get("basePrice"), int(v.get("discountPercent") or 0)
    color, weight, gold = v.get("color") or {}, v.get("weight") or {}, v.get("goldBasePrice")
    out = {
        "id": int(v["id"]),
        "shade": color.get("name"),
        "size": f"{weight['value']} {weight.get('unit') or ''}".strip() if weight.get("value") else None,
        "final_price": final or None,
        "price": (final if not pct else price) or None,
        "discount_pct": pct,
        "in_stock": bool(v.get("isSalable")),
        "max_qty": v.get("limit"),
        "lead_days": v.get("leadTime"),
        "seller": v.get("vendorDisplayName") or "خانومی",
    }
    if badges := _badges(v.get("flags")):
        out["badges"] = badges
    if v.get("giftVariantNameFa"):
        out["gift"] = v["giftVariantNameFa"]
    if gold:
        out["gold"] = {
            "price_per_gram_18k": gold.get("goldPrice"),
            "making_fee_pct": gold.get("makingFeePercent"),
            "margin_pct": gold.get("marginPercent"),
            "vat_pct": gold.get("vatPercent"),
            "price_valid_until": gold.get("goldPriceExpiration"),
        }
    return out


def _clip(text: str, n: int) -> str | None:
    return (text[:n] + "…" if len(text) > n else text) or None
