# coding=utf-8
# Copyright 2022 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A module that mines size from product data.

This module mines the size from product data when google product category is in
the list below:
- Apparel & Accessories > Clothing
- Apparel & Accessories > Shoes

References
- Google Merchant Center Help Center:
https://support.google.com/merchants/answer/6324492?hl=en
"""

import logging
import re
from typing import Any, Dict, Optional
from flask import current_app

import jaconv
import MeCab

import constants
from util import gpc_id_to_string_converter
from util import optimization_util

_ATTRIBUTES_TO_INSPECT = ('title', 'description')

_GPC_STRING_TO_ID_MAPPING_CONFIG_FILE_NAME: str = 'gpc_string_to_id_mapping_{}'

_NUMERIC_SIZE_INDICATORS = ('size', 'サイズ')

_JA_NOUN = '名詞'
_JA_SYMBOL = 'サ変接続'

_SUPPORTED_LANGUAGES = (constants.LANGUAGE_CODE_DE, constants.LANGUAGE_CODE_EN,
                        constants.LANGUAGE_CODE_JA)


class SizeMiner(object):
  """A class that mines size from product data."""

  _gpc_id_to_string_converter: Optional[
      gpc_id_to_string_converter.GPCConverter] = None
  _language: Optional[str] = None
  _mecab_tagger: Optional[MeCab.Tagger] = None

  def __init__(self, language: str, country: str) -> None:
    """Initializes SizeMiner.

    Args:
      language: The configured language code.
      country: The configured country code.
    """
    super(SizeMiner, self).__init__()
    self._country = country
    self._gpc_id_to_string_converter = gpc_id_to_string_converter.GPCConverter(
        _GPC_STRING_TO_ID_MAPPING_CONFIG_FILE_NAME.format(language))
    self._language = language
    self._mecab_tagger = current_app.config.get('MECAB')

  def mine_size(self, product: Dict[str, Any]) -> Optional[str]:
    """Mines size from product fields.

    Args:
      product: A dictionary containing product data.

    Returns:
      A string representing size if it was able to be mined, otherwise None.
    """
    if 'sizes' in product and product['sizes'] and product['sizes'][0]:
      return product['sizes'][0]

    google_product_category = product.get('googleProductCategory', '')
    gpc_string = self._gpc_id_to_string_converter.convert_gpc_id_to_string(
        google_product_category)

    if self._language in _SUPPORTED_LANGUAGES:
      # Mines clothing size.
      if optimization_util.is_particular_google_product_category(
          gpc_string, constants
          .GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_CLOTHING_KEYWORDS,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_CLOTHING_IDS):
        return self._mine_clothing_size(product)

      # Mines shoes size.
      if optimization_util.is_particular_google_product_category(
          gpc_string,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_SHOES_KEYWORDS,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_SHOES_IDS):
        return self._mine_shoe_size(product)
    else:
      logging.warning(
          'The optimizer did not mine size because the language %s is not supported.',
          self._language)
      return None

  def is_size_in_attribute(self, product: Dict[str, Any],
                           attribute: str) -> bool:
    """Checks if the size in a given attribute.

    Args:
      product: A dictionary containing product data.
      attribute: An attribute of the product to be inspected.

    Returns:
      Whether the size is in the attribute.
    """
    google_product_category = product.get('googleProductCategory', '')
    gpc_string = self._gpc_id_to_string_converter.convert_gpc_id_to_string(
        google_product_category)

    if self._language == constants.LANGUAGE_CODE_JA:
      product_attribute_text = product.get(attribute, '')
      if not product_attribute_text:
        return False

      # Mines clothing size.
      if optimization_util.is_particular_google_product_category(
          gpc_string, constants
          .GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_CLOTHING_KEYWORDS,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_CLOTHING_IDS):
        return self._mine_clothing_size_from_attribute(product_attribute_text)

      # Mines shoes size.
      elif optimization_util.is_particular_google_product_category(
          gpc_string,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_SHOES_KEYWORDS,
          constants.GOOGLE_PRODUCT_CATEGORY_APPAREL_ACCESSORIES_SHOES_IDS):
        return self._mine_shoe_size_from_attribute(product_attribute_text)

      else:
        logging.info(
            'The optimizer did not check if the size is in %s because googleProductCategory is not one that needs size.'
        )
        return False
    else:
      logging.warning(
          'The optimizer did not check if the size is in %s because the language %s is not supported.',
          attribute, self._language)
      return False

  def _mine_clothing_size(self, product) -> Optional[str]:
    """Mines the size of the clothing from product fields.

    Args:
      product: A dictionary containing product data.

    Returns:
      A size if it could be mined, otherwise None.
    """
    for attribute in _ATTRIBUTES_TO_INSPECT:
      product_attribute_text = product.get(attribute, '')
      if not product_attribute_text:
        continue
      mined_size = self._mine_clothing_size_from_attribute(
          product_attribute_text)
      if mined_size:
        return mined_size
    return None

  def _mine_clothing_size_from_attribute(self, text: str) -> Optional[str]:
    """Mines the size from attribute based on the configured language.

    Args:
      text: Text to be inspected.

    Returns:
      A size if it could be mined, otherwise None.
    """
    if self._language == constants.LANGUAGE_CODE_JA:
      normalized_text = _normalize_ja_text(text)
      mined_size = self._mine_ja_alphabetic_clothing_size_with_mecab(
          normalized_text)
      if not mined_size:
        mined_size = self._mine_ja_numeric_clothing_size_with_mecab(
            normalized_text)
      return mined_size
    elif self._language == constants.LANGUAGE_CODE_EN:
      mined_size = self._mine_en_clothing_size(text)
      return mined_size
    return None

  def _mine_ja_alphabetic_clothing_size_with_mecab(self,
                                                   text: str) -> Optional[str]:
    """Mines size from the given text for Japanese language.

    Args:
      text: Text to be inspected.

    Returns:
      A size string if one was able to be mined, otherwise None.
    """
    if not self._mecab_tagger:
      logging.warning('Did not mine size because MeCab was not set up.')
      return None

    # Setup valid clothing sizes using regex.
    clothing_size_chars_finder = re.compile(
        constants.CLOTHING_SIZES_REGEX_CHARS, re.IGNORECASE)
    clothing_size_words_finder = re.compile(
        constants.CLOTHING_SIZES_REGEX_WORDS, re.IGNORECASE)

    # Tokenize Japanese-language string, then check tokens against valid sizes.
    node = self._mecab_tagger.parseToNode(text)
    while node:
      token = node.surface
      if not token:
        node = node.next
        continue

      # Validate that the token represents a size based on the regex patterns.
      clothing_size_chars_matched = clothing_size_chars_finder.match(token)
      clothing_size_words_matched = clothing_size_words_finder.match(token)
      if clothing_size_chars_matched or clothing_size_words_matched:
        return token
      node = node.next
    return None

  def _mine_ja_numeric_clothing_size_with_mecab(self,
                                                text: str) -> Optional[str]:
    """Mines size tokens that correspond to size indicators in Japanese.

    This method finds a size indicator word and returns the size value after it.
    e.g. when the input is "T-shirt size:40", it returns "40".

    Args:
      text: Text to be inspected.

    Returns:
      A size if it could be mined, otherwise None.
    """
    if not self._mecab_tagger:
      logging.warning('Did not mine size because MeCab was not set up.')
      return None

    clothing_size_ja_numeric_finder = re.compile(
        constants.NUMERIC_CLOTHING_SIZES_JA_REGEX, re.IGNORECASE)

    indicator_found = False
    node = self._mecab_tagger.parseToNode(text)
    while node:
      size_indicator_candidate = node.surface
      if not node.surface:
        node = node.next
        continue

      if indicator_found:
        rest_of_text = _concat_mecab_nodes_from_node(node)
        rest_of_text_matches = clothing_size_ja_numeric_finder.match(
            rest_of_text)
        if rest_of_text_matches:
          first_matched_result = rest_of_text_matches.group(0)
          return first_matched_result

      # Looks for a matching size term in the text after the size indicator.
      if size_indicator_candidate.lower() in _NUMERIC_SIZE_INDICATORS:
        indicator_found = True
      node = node.next
    return None

  def _mine_en_clothing_size(self, text: str) -> Optional[str]:
    """Mines a size from the given text by scanning words/applying regex.

    Args:
      text: Text to be inspected for size-related words.

    Returns:
      A size if it could be mined, otherwise None.
    """
    clothing_size_regex_chars = constants.CLOTHING_SIZES_REGEX_CHARS
    clothing_size_regex_words = constants.CLOTHING_SIZES_REGEX_WORDS
    clothing_size_chars_finder = re.compile(clothing_size_regex_chars,
                                            re.IGNORECASE)
    clothing_size_words_finder = re.compile(clothing_size_regex_words,
                                            re.IGNORECASE)

    words = text.split()
    for word in words:
      clothing_size_chars_matched = clothing_size_chars_finder.match(word)
      clothing_size_words_matched = clothing_size_words_finder.match(word)
      if clothing_size_chars_matched or clothing_size_words_matched:
        return word.capitalize()
    normalized_text = text.lower()
    for size in constants.ALPHABETIC_CLOTHING_SIZES_EN_UNISIZE:
      if size.lower() in normalized_text:
        return size
    return None

  def _mine_shoe_size(self, product) -> Optional[str]:
    """Mines the size of the shoe from product fields.

    Args:
      product: A dictionary containing product data.

    Returns:
      A size if it could be mined, otherwise None.
    """
    for attribute in _ATTRIBUTES_TO_INSPECT:
      product_attribute_text = product.get(attribute, '')
      if not product_attribute_text:
        continue
      else:
        mined_size = self._mine_shoe_size_from_attribute(product_attribute_text)
        if mined_size:
          return mined_size
    return None

  def _mine_shoe_size_from_attribute(self, text: str) -> Optional[str]:
    """Mines the size from attribute based on the configured language.

    Args:
      text: Text to be inspected.

    Returns:
      A size if it could be mined, otherwise None.
    """
    if self._language == constants.LANGUAGE_CODE_JA:
      text = _normalize_ja_text(text)
      mined_size = self._mine_number_shoe_size_with_range(
          text, constants.MINIMUM_SHOE_SIZE_JP, constants.MAXIMUM_SHOE_SIZE_JP)
      return mined_size
    elif self._language == constants.LANGUAGE_CODE_EN:
      if self._country == constants.COUNTRY_CODE_US:
        mined_size = self._mine_number_shoe_size_with_range(
            text, constants.MINIMUM_SHOE_SIZE_US,
            constants.MAXIMUM_SHOE_SIZE_US)
        return mined_size
      else:
        logging.warning(
            'The shoe-size mining feature currently does not support country %s with language %s.',
            self._country, self._language)
    return None

  def _mine_number_shoe_size_with_range(self, text: str, min_size: float,
                                        max_size: float) -> Optional[str]:
    """Mines the size in the valid number format and the range.

    This methods mines sizes under the condition below:
    - min_size <= size <= mix_size
    - Size is an integer or the first decimal place is 0 or 5.
    Examples when min_size = 10 and max_size = 40
    - Recognized as size: 10, 27, 27.0, 27.5, 40
    - Not recognized as size: 9, 27.1, 41

    Args:
      text: Text to be inspected.
      min_size: The minimum size.
      max_size: The maximum size.

    Returns:
      A size if it could be mined, otherwise None.
    """
    shoe_size_pattern = r'((?<!\d)\d{1,2}\.[05](?!\d)|(?<![\.\d])\d{1,2}(?![\.\d]))'
    size_finder = re.compile(shoe_size_pattern)
    size_candidates = size_finder.findall(text)
    for size_candidate in size_candidates:
      if min_size <= float(size_candidate) <= max_size:
        return size_candidate
    return None


def _normalize_ja_text(text: str) -> str:
  """Converts full-width alphabet/digit characters to half-width characters.

  Args:
    text: Text to be transformed.

  Returns:
    Transformed text.
  """
  return jaconv.z2h(text, kana=False, ascii=True, digit=True)


def _concat_mecab_nodes_from_node(node: object) -> str:
  """Generates a concatenated string of all nodes in the Mecab Node object."""
  node_values = []
  while node:
    node_values.append(node.surface)
    node = node.next
  return ''.join(node_values).strip()
