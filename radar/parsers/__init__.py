from . import cspdcl, s3waas, saral, servicesetu, sitemap, sric_kgp, watch

PARSERS = {"s3waas": s3waas.parse, "watch": watch.parse, "servicesetu": servicesetu.parse,
           "sitemap": sitemap.parse, "cspdcl": cspdcl.parse,
           "saral": saral.parse, "sric_kgp": sric_kgp.parse}


def parse(source, html: str, page_url: str):
    return PARSERS[source.kind](html, page_url, source)
