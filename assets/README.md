# Default social preview

`og-card.html` is the editable HTML/CSS source for `og-card.png`.

The PNG is a browser screenshot at **1200 × 630 CSS pixels**, device scale **1**. It uses local Times New Roman and native link styling, with no external fonts or image generation.

To update it:

1. Edit the HTML source and open it through the local HTTP server.
2. Set the browser viewport to 1200 × 630 and device scale to 1.
3. Capture the page as PNG, without browser controls, at the original size.
4. Save the result as `assets/og-card.png` and commit both files.

The homepage and archive renderer reference `https://darkolorin.com/assets/og-card.png`. Articles with an original image continue to use that image. The feed workflow regenerates page metadata, but does not recapture this PNG.
