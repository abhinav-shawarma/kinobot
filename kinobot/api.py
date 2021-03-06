#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# License: GPL
# Author : Vitiko

import logging
import os
import time

from datetime import datetime
from functools import reduce
from textwrap import wrap

import kinobot.exceptions as exceptions

from kinobot.db import get_list_of_movie_dicts, get_list_of_episode_dicts
from kinobot.comments import dissect_comment
from kinobot.frame import draw_quote
from kinobot.gif import handle_gif_request
from kinobot.palette import get_palette_legacy
from kinobot.request import Request
from kinobot.utils import (
    check_image_list_integrity,
    get_collage,
    is_episode,
    is_parallel,
    homogenize_images,
)

from kinobot import FRAMES_DIR

WEBSITE = "https://kino.caretas.club"
GITHUB_REPO = "https://github.com/vitiko98/kinobot"


logger = logging.getLogger(__name__)


def save_images(pil_list, movie_dict, comment_dict):
    """
    :param pil_list: list PIL.Image objects
    :param movie_dict: movie dictionary
    :param movie_dict: comment/request dictionary
    """
    directory = os.path.join(FRAMES_DIR, str(time.time()))
    os.makedirs(directory, exist_ok=True)

    text = (
        f"{movie_dict.get('title')} ({movie_dict.get('year')}) *** "
        f"{comment_dict.get('type')} {comment_dict.get('content')}"
    )
    with open(os.path.join(directory, "info.txt"), "w") as text_info:
        text_info.write("\n".join(wrap(text, 70)))

    names = [os.path.join(directory, f"{n[0]:02}.jpg") for n in enumerate(pil_list)]

    for image, name in zip(pil_list, names):
        image.save(name)
        logger.info(f"Saved: {name}")

    return names


def get_alt_title(frame_objects, is_episode=False):
    """
    :param frame_objects: list of request.Request objects
    :param is_episode
    """
    item_dicts = [item[0].movie for item in frame_objects]
    if is_episode:
        titles = [
            (
                f"{item['title']} - Season {item['season']}"
                f", Episode {item['episode']}"
            )
            for item in item_dicts
        ]
    else:
        titles = [f"{item['title']} " f"({item['year']})" for item in item_dicts]

    return f"{' | '.join(titles)}\nCategory: Kinema Parallels"


def get_description(item_dictionary, request_dictionary, extra_info=True):
    """
    :param item_dictionary: movie/episode dictionary
    :param request_dictionary
    """
    if request_dictionary["is_episode"] and not request_dictionary["parallel"]:
        title = (
            f"{item_dictionary['title']} - Season {item_dictionary['season']}"
            f", Episode {item_dictionary['episode']}\nWriter: "
            f"{item_dictionary['writer']}"
        )
    elif request_dictionary["parallel"]:
        title = request_dictionary["parallel"]
    else:
        pretty_title = item_dictionary["title"]

        if (
            item_dictionary["title"].lower()
            != item_dictionary["original_title"].lower()
            and len(item_dictionary["original_title"]) < 45
        ):
            pretty_title = (
                f"{item_dictionary['original_title']} [{item_dictionary['title']}]"
            )

        title = (
            f"{pretty_title} ({item_dictionary['year']})\nDirector: "
            f"{item_dictionary['director']}\nCategory: {item_dictionary['category']}"
        )

    if extra_info:
        time_ = datetime.now().strftime("Automatically executed at %H:%M GMT-4")
        return (
            f"{title}\n\nRequested by {request_dictionary['user']} ({request_dictionary['type']} "
            f"{request_dictionary['comment']})\n\n{time_}\nThis bot is open source: {GITHUB_REPO}"
        )

    return title


def generate_frames(comment_dict, is_multiple=True):
    """
    :param comment_dict: comment dictionary
    :param is_multiple
    """
    movies = get_list_of_movie_dicts()
    episodes = get_list_of_episode_dicts()

    for frame in comment_dict["content"]:
        request = Request(
            frame,
            movies,
            episodes,
            comment_dict,
            is_multiple,
        )
        if request.is_minute:
            request.handle_minute_request()
        else:
            try:
                request.handle_quote_request()
            except exceptions.ChainRequest:
                request.handle_chain_request()
                yield request
                break
        yield request


def handle_commands(comment_dict, is_multiple=True, on_demand=False):
    """
    :param comment_dict: request dictionary
    :param is_multiple
    :param on_demand
    """
    requests = []
    if comment_dict["parallel"]:
        for parallel in comment_dict["parallel"]:
            new_request = dissect_comment(f"!req {parallel}")
            new_request["movie"] = new_request["title"]
            new_request["content"] = new_request["content"]
            new_request["comment"] = new_request["comment"]
            new_request["id"] = comment_dict["id"]
            new_request["parallel"] = comment_dict["parallel"]
            new_request["user"] = comment_dict["user"]
            new_request["is_episode"] = comment_dict["is_episode"]
            new_request["verified"] = comment_dict["verified"]
            new_request["type"] = "!parallel"
            new_request["on_demand"] = on_demand
            requests.append(new_request)
    else:
        requests = [comment_dict]

    for request in requests:
        yield list(
            generate_frames(request, is_multiple if len(requests) == 1 else True)
        )


def get_images(comment_dict, is_multiple):
    """
    :param comment_dict: request dictionary
    :param is_multiple: ignore palette generator
    """
    frames = list(handle_commands(comment_dict, is_multiple))
    alt_title = None

    if comment_dict["parallel"]:
        final_frames = []
        homogenized = homogenize_images([frame[0].pill[0] for frame in frames])

        for index, frame in enumerate(frames):
            if frame[0].quote:
                final_frames.append(draw_quote(homogenized[index], frame[0].quote))
            else:
                final_frames.append(homogenized[index])

        single_image_list = [get_collage(final_frames, False)]
        alt_title = get_alt_title(frames, comment_dict["is_episode"])
        frames = frames[0]

    else:
        frames = frames[0]

        if comment_dict["type"] == "!palette":
            single_image_list = [get_palette_legacy(frames[0].pill[0])]
        else:
            final_image_list = [im.pill for im in frames]
            single_image_list = reduce(lambda x, y: x + y, final_image_list)

        check_image_list_integrity(single_image_list)

        if 1 < len(single_image_list) < 4:
            single_image_list = [get_collage(single_image_list, False)]

    saved_images = save_images(single_image_list, frames[0].movie, comment_dict)

    return saved_images, frames, alt_title


def handle_request(request_dict, facebook=True):
    """
    :param request_list: request dictionaries
    :param facebook: add extra info to description key
    """
    request_dict["is_episode"] = is_episode(request_dict["comment"])
    request_dict["parallel"] = is_parallel(request_dict["comment"])

    if len(request_dict["content"]) > 10:
        raise exceptions.TooLongRequest

    logger.info(
        f"Request comment: {request_dict['comment']}; "
        f"command: {request_dict['type']}"
    )

    if request_dict["type"] == "!gif":
        if facebook:
            raise exceptions.InvalidRequest(request_dict["type"])

        movie, final_imgs = handle_gif_request(request_dict, get_list_of_movie_dicts())
        alt_title = None
    else:
        is_multiple = len(request_dict["content"]) > 1
        final_imgs, frames, alt_title = get_images(request_dict, is_multiple)
        movie = frames[0].movie

    request_dict["parallel"] = alt_title
    request_description = get_description(movie, request_dict, facebook)

    logger.info("Request finished successfully")

    return {
        "description": request_description,
        "images": final_imgs,
        "final_request_dict": request_dict,
        "movie_dict": movie,
    }
