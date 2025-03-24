from PIL import Image
from colormath.color_conversions import convert_color
import sqlite3
import sqlite_vec
import struct
from colormath.color_objects import sRGBColor, LabColor, HSLColor
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from tqdm import tqdm
import requests

class DatabaseUtil:
  def __init__(self):
    self.db = DatabaseUtil.get_db()

  def get_db():
    db = sqlite3.connect("median_colors.db")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db

  def reset_card_table(self):
    try:
      self.db.execute("DROP TABLE card")
      self.db.execute(
      """
        CREATE VIRTUAL TABLE IF NOT EXISTS card USING vec0(
          image_uri text,
          lab_mean float[3],
        )
      """)
    except sqlite3.OperationalError as e:
      print(f"Database error: {e}")

  def get_first_available_rowid(self):
    try:
      with self.db:
        cursor = self.db.cursor()
        cursor.execute(f"SELECT MAX(rowid) FROM card")
        row_num = cursor.fetchone()[0]
        if row_num == None:
          return 0
        else:
          return row_num + 1
    except sqlite3.Error as e:
      print(f"Database error: {e}")

  def query_image_uri(self, image_uri):
    try:
      with self.db:
        cursor = self.db.cursor()
        cursor.execute(f"SELECT * FROM card WHERE image_uri = '{image_uri}' LIMIT 1")
        result = cursor.fetchone()
        return result
    except sqlite3.Error as e:
      print(f"Database error: {e}")
      return False

  def prune_bulk_unique_art_json(self, bulk_json_list):
    pruned_bulk_json_list = []
    for card in bulk_json_list:
      if (
        card["set_type"] == "token"
        or card["set_type"] == "memorabilia"
        or card["set_type"] == "alchemy"
        or card["set_type"] == "vanguard"):
        continue

      pruned_bulk_json_list.append(card)
    return pruned_bulk_json_list

  def serialize_f32(vector) -> bytes:
    """serializes a list of floats into a compact "raw bytes" format"""
    return struct.pack("%sf" % len(vector), *vector)

  def deserialize_f32(byte_string):
    """serializes a list of floats into a compact "raw bytes" format"""
    return struct.unpack('<3f', byte_string)

  # takes ~20 minutes
  def populate_vector_table(self, items):
    first_available_row_id = self.get_first_available_rowid()
    with self.db:
      for i in range(len(items)):
          self.db.execute(
              """
                INSERT INTO card (rowid, image_uri, lab_mean) VALUES (?, ?, ?)
              """,
              [i+first_available_row_id, items[i][0], DatabaseUtil.serialize_f32(items[i][1])]
              )

  def get_closest_lab_mean_row(self, lab_vector):
    rows = self.db.execute(
        """
          SELECT
            image_uri,
            distance
          FROM card 
          WHERE lab_mean MATCH ?
          ORDER BY distance
          LIMIT 1
        """,
        [DatabaseUtil.serialize_f32(lab_vector)],
    ).fetchall()
    return rows

  def get_candidate_lab_mean_rows(self, lab_vector):
    rows = self.db.execute(
        """
          SELECT
            image_uri,
            distance
          FROM card 
          WHERE lab_mean MATCH ?
          ORDER BY distance
          LIMIT 100
        """,
        [DatabaseUtil.serialize_f32(lab_vector)],
    ).fetchall()
    return rows

  def get_mean_lab_vector_of_card(card_img: Image):
    img = card_img.convert('RGB')
    img_x, img_y = card_img.size[0], card_img.size[1]
    total_rgb = [0.0, 0.0, 0.0]
    for x in range(img_x):
      for y in range(img_y):
        pixel = img.getpixel((x, y))
        total_rgb[0] += pixel[0]
        total_rgb[1] += pixel[1]
        total_rgb[2] += pixel[2]
    mean_rgb = [round(i/(img_x*img_y)) for i in total_rgb]
    mean_lab = convert_color(sRGBColor(mean_rgb[0], mean_rgb[1], mean_rgb[2], is_upscaled=True), LabColor).get_value_tuple()
    return DatabaseUtil.convert_lab_to_vector(tuple(mean_lab))

  # TODO: move to a vector_util class
  def convert_lab_to_vector(lab):
    return [lab[0]/100.0, (lab[1]+128.0)/(128.0*2.0), (lab[2]+128.0)/(128.0*2.0)]

  # TODO: move to a vector_util class
  def convert_vector_to_lab(vector):
    return LabColor(vector[0]*100, (vector[1] * 128.0 * 2.0) - 128, (vector[2] * 128.0 * 2.0) - 128)

  def bulk_fill_items_p(self, pruned_bulk_json_list):
    with ThreadPoolExecutor() as executor:
      results = list(
        tqdm(
          executor.map(self.process_card, pruned_bulk_json_list),
          total=len(pruned_bulk_json_list),
          desc = "bulk_fill_items_p"
        )
      )
    return results

  # TODO: move to a vector_util class
  def process_card(card):
    faces = [card]
    if "card_faces" in card and "image_uris" not in card:
      faces = card["card_faces"]
    for face in faces:
      border_crop_img_uri = face["image_uris"]["border_crop"]
      small_img_uri = face["image_uris"]["small"] # using small_img is 10x faster, ~20min
      small_img = Image.open(BytesIO(requests.get(small_img_uri).content))
      return (border_crop_img_uri, DatabaseUtil.get_mean_lab_vector_of_card(small_img))

  def get_closest_card_img(self, lab_vector):
    row = self.get_closest_lab_mean_row(lab_vector)[0]
    # TODO: implement retry
    return Image.open(BytesIO(requests.get(row[0]).content))

  def get_candidate_card_rows(self, lab_vector, dist_t=.025):
    candidate_rows = self.get_candidate_lab_mean_rows(lab_vector = lab_vector)
    closest_distance = candidate_rows[0][1]
    start_idx, cutoff_idx = 0, 1
    while cutoff_idx < len(candidate_rows) and candidate_rows[cutoff_idx][1] - closest_distance < dist_t:
      cutoff_idx += 1
    return candidate_rows[start_idx:cutoff_idx]