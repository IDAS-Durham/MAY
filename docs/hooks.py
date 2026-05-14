import re

LOGO_HTML = """<p align="center">
  <img src="assets/images/May_logo_dark.png" alt="MAY logo" width="300" class="logo-light-mode">
  <img src="assets/images/May_logo_white.png" alt="MAY logo" width="300" class="logo-dark-mode">
</p>

"""


def on_page_markdown(markdown, page, **kwargs):
    if page.file.src_path == "README.md":
        page.title = 'Home'
        markdown = LOGO_HTML + markdown
    return markdown


def on_post_page(output, page, **kwargs):
    if page.file.src_path == "README.md":
        output = re.sub(r'<h1[^>]*>.*?</h1>', '', output, count=1)
    return output
