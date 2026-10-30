from . import s3waas, servicesetu, sitemap, watch

PARSERS = {"s3waas": s3waas.parse, "watch": watch.parse, "servicesetu": servicesetu.parse,
           "sitemap": sitemap.parse}


def parse(source, html: str, page_url: str):
    return PARSERS[source.kind](html, page_url, source)
