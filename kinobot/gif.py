#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import os

import cv2

from kinobot.exceptions import InvalidRequest
from kinobot.frame import cv2_to_pil, draw_quote, fix_dar, get_dar, center_crop_image
from kinobot.utils import convert_request_content, get_subtitle
from kinobot.request import find_quote, guess_subtitle_chain, search_movie

from kinobot import FRAMES_DIR

logger = logging.getLogger(__name__)


def sanity_checks(subtitle_list=[], range_=None):
    if len(subtitle_list) > 4:
        raise InvalidRequest(len(subtitle_list))

    if range_:
        if abs(range_[0] - range_[1]) > 7:
            raise InvalidRequest(range_)


def scale_to_gif(pil_image):
    w, h = pil_image.size

    inc = 0.5
    while True:
        if w * inc < 550:
            break
        inc -= 0.1

    return pil_image.resize((int(w * inc), int(h * inc)))


def start_end_gif(fps, sub_dict=None, range_=None):
    if sub_dict:
        extra_frames_start = int(fps * (sub_dict["start_m"] * 0.000001))
        extra_frames_end = int(fps * (sub_dict["end_m"] * 0.000001))
        frame_start = int(fps * sub_dict["start"]) + extra_frames_start
        frame_end = int(fps * sub_dict["end"]) + extra_frames_end
        return (frame_start, frame_end)

    return (int(fps * range_[0]), int(fps * range_[1]))


def get_image_list_from_range(path, range_=(0, 7), dar=None):
    """
    :param path: video path
    :param subs: range of seconds
    :param dar: display aspect ratio from video
    """
    sanity_checks(range_=range_)

    logger.info("About to extract GIF for range %s", range_)

    capture = cv2.VideoCapture(path)
    if not dar:
        dar = get_dar(path)

    fps = capture.get(cv2.CAP_PROP_FPS)
    start, end = start_end_gif(fps, range_=range_)

    logger.info(f"Start: {start} - end: {end}; diff: {start - end}")
    for i in range(start, end, 3):
        capture.set(1, i)
        yield scale_to_gif(
            center_crop_image(cv2_to_pil(fix_dar(path, capture.read()[1], dar)))
        )


def get_image_list_from_subtitles(path, subs=[], dar=None):
    """
    :param path: video path
    :param subs: list of subtitle dictionaries
    :param dar: display aspect ratio from video
    """
    sanity_checks(subs)

    logger.info(f"Subtitles found: {len(subs)}")

    capture = cv2.VideoCapture(path)
    if not dar:
        dar = get_dar(path)

    fps = capture.get(cv2.CAP_PROP_FPS)
    for subtitle in subs:
        start, end = start_end_gif(fps, sub_dict=subtitle)
        end += 10

        logger.info(f"Start: {start} - end: {end}; diff: {start - end}")
        for i in range(start, end, 3):
            capture.set(1, i)
            pil = scale_to_gif(cv2_to_pil(fix_dar(path, capture.read()[1], dar)))
            yield draw_quote(center_crop_image(pil), subtitle["message"])


def image_list_to_gif(images, filename="sample.gif"):
    """
    :param images: list of PIL.Image objects
    :param filename: output filename
    """
    logger.info(f"Saving GIF ({len(images)} images)")

    images[0].save(filename, format="GIF", append_images=images[1:], save_all=True)

    logger.info(f"Saved: {filename}")


def get_range(content):
    """
    :param content: string from request square bracket
    """
    seconds = [convert_request_content(second.strip()) for second in content.split("-")]

    if any(isinstance(second, str) for second in seconds):
        logger.info("String found. Quote request")
        return content

    if len(seconds) != 2:
        raise InvalidRequest(content)

    logger.info("Good gif timestamp request")
    return tuple(seconds)


def get_quote_list(subtitle_list, dictionary):
    """
    :param subtitle_list: list of srt.Subtitle objects
    :param dictionary: request dictionary
    """
    chain = guess_subtitle_chain(subtitle_list, dictionary)
    if not chain:
        chain = []
        for quote in dictionary["content"]:
            chain.append(find_quote(subtitle_list, quote))

    return chain


def handle_gif_request(dictionary, movie_list):
    """
    Handle a GIF request. Return movie dictionary and GIF file (inside a list
    to avoid problems with the API).

    :param dictionary: request dictionary
    :param movie_list: list of movie dictionaries
    """
    possible_range = get_range(dictionary["content"][0])
    movie = search_movie(movie_list, dictionary["movie"], raise_resting=False)
    subtitle_list = get_subtitle(movie)

    if isinstance(possible_range, tuple):
        image_list = list(get_image_list_from_range(movie["path"], possible_range))
    else:
        sub_list = get_quote_list(subtitle_list, dictionary)
        image_list = list(get_image_list_from_subtitles(movie["path"], sub_list))

    filename = os.path.join(FRAMES_DIR, f"{dictionary['id']}.gif")
    image_list_to_gif(image_list, filename)

    return movie, [filename]
