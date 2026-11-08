from . import cspdcl, s3waas, saral, servicesetu, sitemap, watch

PARSERS = {"s3waas": s3waas.parse, "watch": watch.parse, "servicesetu": servicesetu.parse,
           "sitemap": sitemap.parse, "cspdcl": cspdcl.parse,
           "saral": saral.parse}


def parse(source, html: str, page_url: str):
    return PARSERS[source.kind](html, page_url, source)
