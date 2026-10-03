"""Readable passphrases for password-protected share links.

Four words drawn with :mod:`secrets` from a fixed list of short, common,
unambiguous English words, joined by hyphens: ``maple-otter-crisp-lunar``.
Easy to read out or type from a message, and — with the per-link unlock rate
limit in :mod:`backend.services.public_links` — far beyond online guessing
(the list has over 480 words, so four of them give about 35.7 bits).
"""

from __future__ import annotations

import secrets

WORDS = tuple(sorted(set("""
acorn adapt agent alarm album alert alpha amber angle ankle apple april apron arena argue arrow aspen atlas
attic audio autumn avoid awake badge bagel baker balmy banjo barley basil basin batch beach beacon beard
bench berry birch bison blade blank blaze blend bloom blues board boat bonus boost booth bound bowl brain
brass brave bread brick brief broom brush bucket buddy bugle build bunch cabin cable cactus camel camera
canal candle canoe canyon cargo carpet carrot castle cedar cello chalk charm chart cheek cherry chess chief
chili chimney choir cider cinema circle civic clam clay clever cliff climb clock cloud clover coast cobalt
cocoa comet comic coral corner cotton couch cove crane crayon cream crest cricket crisp crown crumb cubic
cumin curve cycle daisy dance delta denim depot desert dial diary dingo diver dock dolphin domino donut dove
dragon drift drum dune eagle easel ebony echo eclipse elbow elder ember emerald empty engine epoch equal
fable fabric falcon fancy feast fern ferry fiber field fiesta finch fjord flag flame flash fleet flint flute
focus foggy forest forge fossil frame fresh frost fruit fudge gadget galaxy garden garlic gate gecko gentle
giant ginger glade glass glide globe glove golden goose grain grape gravel green grove guava guest guitar
gully habit hammer harbor harp hatch haven hazel heron hiker hinge hobby honey hoop horizon hotel humble
husky igloo indigo inlet iris island ivory jacket jaguar jasmine jelly jewel jigsaw jolly journey juice
jungle kayak kettle kiosk kite kiwi koala ladder ladle lagoon lake lantern laser latch lava lemon lens
level lilac lime linen lion lobby locket lotus lucky lunar lunch lyric magnet mango maple marble market
meadow medal melon mentor merit metal meteor mild mint mirror mocha model monsoon mosaic moss motor
muffin mural music nectar needle nest nickel noble noodle north nova nugget oasis oatmeal ocean olive
onion opal orange orbit orchid otter oven oyster paddle palm panda paper parade parcel parrot pasta
patio peach pearl pebble pecan pedal pelican pepper piano picnic pilot pine pixel plaza plum polar pony
poppy portal potato prairie prism puffin pulse pumpkin puzzle quail quartz quest quiet quill quilt rabbit
radar radio raft rain ramp raven razor recipe reef relay ribbon ridge ripple river robin rocket rodeo
rose rover ruby rugby saddle saffron sage salad salmon salsa sand satin scarf scout season sesame shadow
shell shore shrub sienna signal silk silver sketch skate sled slope smile snack snow solar sonic spark
spice spiral spoon spring sprout squid stable stamp starch steam stone storm stove straw stream sugar
summit sunny swan sweet syrup table tango teapot temple tender thistle thunder tiger timber toast token
topaz torch tower trail tram travel trout truffle tulip tundra turtle tweed twig umber unity upbeat urban
valley vapor velvet vessel violet violin voyage wafer waffle wagon walnut walrus wander wave willow window
winter wizard wombat wonder yacht yarrow yodel yogurt zebra zenith zephyr zinc
""".split())))

WORD_COUNT = 4


def generate(words: int = WORD_COUNT) -> str:
    """A fresh random passphrase, e.g. ``maple-otter-crisp-lunar``."""
    return "-".join(secrets.choice(WORDS) for _ in range(words))
