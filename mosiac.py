from PIL import Image
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
from colormath.color_objects import sRGBColor, LabColor, HSLColor
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from database_util import DatabaseUtil as db_util
import concurrent.futures
import numpy
import random
import requests
from tqdm import tqdm
import threading
import time
import io

# workaround for https://github.com/gtaylor/python-colormath/issues/104
def patch_asscalar(a):
    return a.item()
setattr(numpy, "asscalar", patch_asscalar)

# "Required Headers" https://scryfall.com/docs/api
HEADERS = {'Accept': '*/*', 'User-Agent': 'ScryfallMosaic/1.0'}
# https://scryfall.com/docs/api/bulk-data
BULK_JSON_LIST = requests.get(
  'https://data.scryfall.io/unique-artwork/unique-artwork-20250321212257.json',
  params=None, headers=HEADERS).json()
# dimensions from https://scryfall.com/docs/api/images
CARD_SIZE_TO_DIMENSIONS = {
  "png": (745, 1040),
  "border_crop": (480, 680),
  "large": (672, 936),
  "normal": (488, 680),
  "small": (146, 204),
}

def get_block_xy(img, columns, card_size = "border_crop"):
  block_x = img.size[0]/float(columns)
  block_y = block_x * float(CARD_SIZE_TO_DIMENSIONS[card_size][1])/float(CARD_SIZE_TO_DIMENSIONS[card_size][0])
  return (block_x, block_y)

def get_median_lab_vector_to_block_coords(db, img, columns):
  rgb_ig = img.convert('RGB')
  img_x, img_y = img.size[0], img.size[1] # 745 × 1040
  block_x, block_y = get_block_xy(img, columns)
  ret = {}
  x_pointer = 0.0
  for x in tqdm(range(columns), desc="get_median_lab_vector_to_block_coords"):
    next_x_pointer = x_pointer + block_x
    y_pointer = 0.0
    for y in range(int(img_y/block_y)):
      next_y_pointer = y_pointer + block_y
      x_min, x_max = int(x_pointer), int(next_x_pointer)
      y_min, y_max = int(y_pointer), int(next_y_pointer)
      y_pointer = next_y_pointer

      colors_in_block = []
      for x2 in range(x_min, x_max):
        for y2 in range(y_min, y_max):
          pixel = rgb_ig.getpixel((x2, y2))
          colors_in_block.append(pixel)
      colors_in_block = sorted(colors_in_block, key=lambda x: x[0]+x[1]+x[2])
      median_rgb_list = list(colors_in_block[int(len(colors_in_block)/2)])
      lab_color_tuple = convert_color(
        sRGBColor(median_rgb_list[0], median_rgb_list[1], median_rgb_list[2], is_upscaled=True),
        LabColor).get_value_tuple()
      median_lab_vector = db_util.convert_lab_to_vector(lab_color_tuple)
      if tuple(median_lab_vector) not in ret:
        ret[tuple(median_lab_vector)] = []
      ret[tuple(median_lab_vector)].append((x,y))
    x_pointer = next_x_pointer
  return ret, columns, int(img_y/block_y)

def create_mosaic_p_helper(mosaic_img, dist_t, initial_resize, img_to_paste_coords_item, lock):
  with lock:
    db = db_util()
    for coord in img_to_paste_coords_item[1]:
      median_lab_vector = list(img_to_paste_coords_item[0])
      candidate_rows = db.get_candidate_card_rows(median_lab_vector, dist_t)
      random_row = random.randint(0, len(candidate_rows) - 1)
      for _attempt in range(3):
        try:
            card_image = Image.open(BytesIO(requests.get(candidate_rows[random_row][0]).content))
            card_image = card_image.resize(
              (int(card_image.size[0]*initial_resize), int(card_image.size[1]*initial_resize))
              )
            mosaic_img.paste(
              card_image,
              (int(coord[0]*CARD_SIZE_TO_DIMENSIONS["border_crop"][0]*initial_resize),
               int(coord[1]*CARD_SIZE_TO_DIMENSIONS["border_crop"][1]*initial_resize))
             )
        except:
          continue
        else:
            break

def create_mosaic_p(db, base_img, columns=75, filename="foo", dist_t = .025, initial_resize=.5):
  median_lab_vector_to_block_coords, x, y = get_median_lab_vector_to_block_coords(db, base_img, columns)
  mosaic_image = Image.new(
    "RGB",
    (
      int(x*CARD_SIZE_TO_DIMENSIONS["border_crop"][0] * initial_resize),
      int(y*CARD_SIZE_TO_DIMENSIONS["border_crop"][1] * initial_resize)
    ),
    "white")
  lock = threading.Lock()
  items = median_lab_vector_to_block_coords.items()
  with ThreadPoolExecutor() as executor:
    futures = [executor.submit(create_mosaic_p_helper, mosaic_image, dist_t, initial_resize, item, lock) for item in items]
    #concurrent.futures.wait(futures)
    with tqdm(total=len(futures), desc="create_mosaic_p") as pbar:
      for future in concurrent.futures.as_completed(futures):
        pbar.update(1)
  save_image(mosaic_image, filename)

def save_image(img, filename="foo"):
  for _attempt in range(3):
    try:
      compress(img, filename)
    except:
      time.sleep(1)
      continue
    else:
        break

# https://stackoverflow.com/questions/40587343/python-pil-find-the-size-of-image-without-writing-it-as-a-file
# Compressed image to <10MB and <50MB versions.
def compress(img, filename, scale=.5):
    assert(0.0 < scale < 1.0)
    pbar = tqdm(desc="compress()")
    resized_file = img.resize(
      (int(img.size[0]*scale), int(img.size[1]*scale))
    )
    pbar.update(1)
    saved_50MB = False
    MB_1 = 10**6

    while True:
      with io.BytesIO() as file_bytes:
        resized_file.save(file_bytes, optimize=True, quality=100, format='png')
        if not saved_50MB and file_bytes.tell() < 50*MB_1:
            saved_50MB = True
            resized_file.save(f"{filename}_50MB.png")
        if file_bytes.tell() < 10* MB_1:
            resized_file.save(f"{filename}_10MB.png")
            break
        resized_file = resized_file.resize(
          (int(resized_file.size[0]*scale), int(resized_file.size[1]*scale))
        )
        pbar.update(1)
    pbar.close()

# https://stackoverflow.com/questions/42045362/change-contrast-of-image-in-pil
def change_contrast(img, level):
    factor = (259 * (level + 255)) / (255 * (259 - level))
    def contrast(c):
        return 128 + factor * (c - 128)
    return img.point(contrast)

dbu = db_util()

# dbu.reset_card_table()
# pruned = dbu.prune_bulk_unique_art_json(BULK_JSON_LIST)
# items = dbu.bulk_fill_items_p(pruned)
# dbu.populate_vector_table(items)

# colors = [
#   sRGBColor(0, 0, 0),
#   sRGBColor(1, 1, 1),
#   sRGBColor(1, 0, 0),
#   sRGBColor(0, 1, 0),
#   sRGBColor(0, 0, 1),
# ]
# for rgb_color in colors:
#   lab_color = convert_color(rgb_color, LabColor)
#   print("\n{} = {}".format(rgb_color, lab_color))
#   lab_vector = db_util.convert_lab_to_vector(lab_color.get_value_tuple())
#   candidate_rows = dbu.get_candidate_lab_mean_rows(lab_vector)
#   print(f"  {candidate_rows [0]}")
#   print(f"  {candidate_rows [99]}")

# https://scryfall.com/card/sld/1012a/mana-confluence
#   https://cards.scryfall.io/border_crop/front/f/a/fa4b80b1-fc8d-4da6-964a-3b85451c3049.jpg?1683435879
# https://scryfall.com/card/znr/307/lotus-cobra
#   https://cards.scryfall.io/border_crop/front/1/5/151bdf3a-4445-43b1-8cea-2737c13d9dee.jpg?1604202856
# https://scryfall.com/card/p30m/1F/arcane-signet
#   https://cards.scryfall.io/art_crop/front/e/9/e96d398f-7393-4b8e-9972-2d7c394d23ad.jpg?1697570408
# ""
# M11 Promo https://scryfall.com/card/prm/37598/birds-of-paradise
#   https://cards.scryfall.io/art_crop/front/d/8/d8cd9fb5-c275-45a8-964b-5cfc5754ecce.jpg?1562548465
#   https://cards.scryfall.io/border_crop/front/d/8/d8cd9fb5-c275-45a8-964b-5cfc5754ecce.jpg?1562548465
# https://scryfall.com/search?q=artist%3A%22Wylie+beckert%22
#   https://scryfall.com/card/slp/13/expressive-iteration
#     https://cards.scryfall.io/art_crop/front/2/b/2be401fd-491c-4283-b8b6-1073431205b9.jpg?1706549626
#   https://scryfall.com/card/fdn/312/omniscience
#     https://cards.scryfall.io/art_crop/front/7/c/7c72dced-adae-4c66-af2a-0a1216953ab6.jpg?1730489766

# columns=50: 3:46
# intial_resize = .5, columns=50: 3:17
# intial_resize = .5, columns=200: 54:11
# columns=100: 18:42
# columns=300: 2:07:37

arcane_signet_art_crop = 'https://cards.scryfall.io/art_crop/front/e/9/e96d398f-7393-4b8e-9972-2d7c394d23ad.jpg?1697570408'
bop_border_crop = 'https://cards.scryfall.io/border_crop/front/d/f/df87b2e4-033c-447f-9b52-b67de3e6fe41.jpg?1605361641'
ex_it_ac = 'https://cards.scryfall.io/art_crop/front/2/b/2be401fd-491c-4283-b8b6-1073431205b9.jpg?1706549626'
card_img = Image.open(BytesIO(requests.get(bop_border_crop).content))
col = 50
create_mosaic_p(dbu, card_img, columns=col, filename = f"BoP_col{col}", dist_t=.025)
