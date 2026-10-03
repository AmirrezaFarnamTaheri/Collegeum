<?xml version="1.0" encoding="utf-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" version="5.0" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title><xsl:value-of select="/rss/channel/title"/> — Feed</title>
        <link rel="preconnect" href="https://fonts.googleapis.com"/>
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous"/>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500&amp;family=Newsreader:ital,opsz,wght@0,6..72,500;0,6..72,600;1,6..72,400&amp;display=swap" rel="stylesheet"/>
        <style>
          :root {
            --bg: #F5F1E8;
            --card: #FFFDF7;
            --ink: #1A1916;
            --soft: #625D52;
            --rule: #DDD5C4;
            --acc: #B0401B;
            --acc2: #F2DCCF;
            --serif: 'Newsreader', Georgia, serif;
            --sans: 'Inter', system-ui, sans-serif;
            --mono: 'JetBrains Mono', monospace;
          }
          @media (prefers-color-scheme: dark) {
            :root {
              --bg: #13120F;
              --card: #1B1A16;
              --ink: #EEE9DD;
              --soft: #A29C8E;
              --rule: #34312A;
              --acc: #EC7A4C;
              --acc2: #3A251A;
            }
          }
          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          body {
            background: var(--bg);
            color: var(--ink);
            font: 15px/1.6 var(--sans);
            padding: 40px 20px;
          }
          .wrap {
            max-width: 760px;
            margin: 0 auto;
          }
          header {
            margin-bottom: 32px;
          }
          .back-link {
            display: inline-block;
            font-size: 13.5px;
            color: var(--acc);
            text-decoration: none;
            margin-bottom: 16px;
            font-weight: 500;
          }
          .back-link:hover { text-decoration: underline; }
          h1 {
            font: 600 32px var(--serif);
            letter-spacing: -0.015em;
            margin-bottom: 8px;
          }
          .desc {
            color: var(--soft);
            font-size: 15px;
            margin-bottom: 20px;
          }
          .feed-notice {
            background: var(--card);
            border: 1px solid var(--rule);
            border-left: 3px solid var(--acc);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 32px;
            font-size: 13.5px;
            color: var(--soft);
          }
          .feed-notice b { color: var(--ink); }
          .feed-notice code {
            font-family: var(--mono);
            font-size: 12px;
            background: var(--bg);
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid var(--rule);
            display: inline-block;
            margin-top: 4px;
            word-break: break-all;
          }
          .item {
            background: var(--card);
            border: 1px solid var(--rule);
            border-radius: 12px;
            padding: 18px 20px;
            margin-bottom: 14px;
          }
          .item h2 {
            font: 600 18px/1.35 var(--serif);
            margin-bottom: 6px;
          }
          .item h2 a {
            color: var(--ink);
            text-decoration: none;
          }
          .item h2 a:hover {
            color: var(--acc);
          }
          .item p {
            font-size: 14px;
            color: var(--soft);
            line-height: 1.55;
          }
          .meta {
            font-size: 12px;
            font-family: var(--mono);
            color: var(--soft);
            margin-top: 10px;
          }
        </style>
      </head>
      <body>
        <div class="wrap">
          <header>
            <a class="back-link" href="./">← Return to Collegeum</a>
            <h1><xsl:value-of select="/rss/channel/title"/></h1>
            <p class="desc"><xsl:value-of select="/rss/channel/description"/></p>
            <div class="feed-notice">
              <b>RSS Web Feed:</b> To subscribe in a feed reader (NetNewsWire, Feedly, Reeder, etc.), copy this URL:
              <br/>
              <code><xsl:value-of select="/rss/channel/link"/>/feed.xml</code>
            </div>
          </header>

          <main>
            <xsl:for-each select="/rss/channel/item">
              <article class="item">
                <h2>
                  <a>
                    <xsl:attribute name="href">
                      <xsl:value-of select="link"/>
                    </xsl:attribute>
                    <xsl:value-of select="title"/>
                  </a>
                </h2>
                <p><xsl:value-of select="description"/></p>
                <div class="meta">
                  <xsl:value-of select="pubDate"/>
                </div>
              </article>
            </xsl:for-each>
          </main>
        </div>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
