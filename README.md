# ScryfallMosaic

<a href="https://scryfall.com/card/pm11/165%E2%98%85/birds-of-paradise"><picture>
<img src="https://github.com/TsaoMD/ScryfallMosaic/blob/main/BoP_col50_10MB.png" alt="Birds of Paradise 50 column <10MB mosaic" width="480" height="680">
</picture></a>
<a href="https://scryfall.com/card/pm11/165%E2%98%85/birds-of-paradise"><picture>
<img src="https://github.com/TsaoMD/ScryfallMosaic/blob/main/BoP_col300_10MB.png" alt="Birds of Paradise 300 column <10MB mosaic" width="480" height="680">
</picture></a>

ScryfallMosaic creates mosaics of images using [Magic: the Gathering](https://magic.wizards.com/en) card art. Card images are from the [Scryfall API](https://scryfall.com/docs/api).

Inspired by [@NewbieIndieGameDev](https://www.youtube.com/@NewbieIndieGameDev)'s [Pokémon Card Mosaic video](https://www.youtube.com/watch?v=ZRUCJFyFWJQ&list=LL&index=1).
There's also [Creating a “Magic: the Gathering” Artwork Mosaic](https://mattjo.medium.com/creating-a-magic-the-gathering-artwork-mosaic-f415ec2886fe) by Matthew Johnson, but it uses card art, not full card images.

## Design Overview
Create a vector database (via [sqlite-vec](https://github.com/asg017/sqlite-vec)) of the mean LAB color value of every unique MTG card art.
* Prune ["memoribilia"](https://scryfall.com/search?as=grid&extras=true&order=name&q=st%3Amemorabilia&unique=cards), ["token"](https://scryfall.com/search?q=st%3Atoken&unique=cards&as=grid&order=name), ["alchemy"](https://scryfall.com/search?q=st%3Aalchemy&unique=cards&as=grid&order=name), and ["vanguard"](https://scryfall.com/search?as=grid&extras=true&order=name&q=st%3Avanguard&unique=cards) set cards from the list.
* Takes about ~20 minutes with parallelization on my [AMD Ryzen 5 3600 6-Core Processor](https://www.cpubenchmark.net/cpu.php?cpu=AMD+Ryzen+5+3600&id=3481) to process the remaining ~43k cards.

Divide the reference image into a grid of MTG card-sized blocks.

Get the median LAB color of each block.
* [CIELAB color space](https://en.wikipedia.org/wiki/CIELAB_color_space#Advantages) "is designed to approximate human vision", unlike RGB.
* We use the median of the block, not the mean, because the mean results in [duller greyer tones](https://www.youtube.com/watch?v=ZRUCJFyFWJQ&t=142s).

For each block's median color, find a top candidate in the candidate with the closest matching mean color.
* We use the mean of the card in the database, not the median. Using the median results in these [Tarkir: Dragonstorm ink cards](https://scryfall.com/card/tdm/331/voice-of-victory) as the top candidates for black, which don't look good.

Condense the final mosaic image in to <10MB (Discord file upload limit) and <50MB (Github file upload limit) versions.

For a 480x680 pixel ([Scryfall `border_crop` image](https://scryfall.com/docs/api/images)) reference image, 50 columns takes <4 minutes. 300 columns takes ~2 hours.
