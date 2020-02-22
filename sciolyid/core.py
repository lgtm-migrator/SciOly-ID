# core.py | functions for getting media from a GitHub repo
# Copyright (C) 2019-2020  EraserBird, person_v1.32, hmmm

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import base64
import concurrent.futures
import os
import random
import shutil

import discord
from git import Repo

import sciolyid.config as config
from sciolyid.data import GenericError, database, get_category, logger

# Valid file types
valid_image_extensions = {"jpg", "png", "jpeg", "gif"}


async def send_image(ctx, item: str, on_error=None, message=None):
    """Gets a picture and sends it to the user.

    `ctx` - Discord context object\n
    `item` (str) - picture to send\n
    `on_error` (function)- function to run when an error occurs\n
    `message` (str) - text message to send before picture\n
    """
    if item == "":
        logger.error(f"error - {config.options['id_type']} is blank")
        await ctx.send(
            f"**There was an error fetching {config.options['id_type']}.**\n*Please try again.*"
        )
        if on_error is not None:
            on_error(ctx)
        return

    delete = await ctx.send("**Fetching.** This may take a while.")
    # trigger "typing" discord message
    await ctx.trigger_typing()

    try:
        response = await get_image(ctx, item)
    except GenericError as e:
        await delete.delete()
        await ctx.send(
            f"**An error has occurred while fetching images.**\n*Please try again.*\n**Reason:** {str(e)}"
        )
        logger.exception(e)
        if on_error is not None:
            on_error(ctx)
        return

    filename = str(response[0])
    extension = str(response[1])
    statInfo = os.stat(filename)
    if statInfo.st_size > 4000000:  # another filesize check (4mb)
        await delete.delete()
        await ctx.send("**Oops! File too large :(**\n*Please try again.*")
    else:

        if message is not None:
            await ctx.send(message)

        # change filename to avoid spoilers
        file_obj = discord.File(filename, filename=f"image.{extension}")
        await ctx.send(file=file_obj)
        await delete.delete()


async def get_image(ctx, item):
    """Chooses an image from a list of images.

    This function chooses a valid image to pass to send_image().
    Valid images are based on file extension and size. (8mb discord limit)

    Returns a list containing the file path and extension type.

    `ctx` - Discord context object\n
    `item` (str) - item to get image of\n
    """

    images = await get_files(item)
    logger.info("images: " + str(images))
    prevJ = int(str(database.hget(f"channel:{str(ctx.channel.id)}", "prevJ"))[2:-1])
    # Randomize start (choose beginning 4/5ths in case it fails checks)
    if images:
        j = (prevJ + 1) % len(images)
        logger.info("prevJ: " + str(prevJ))
        logger.info("j: " + str(j))

        for x in range(0, len(images)):  # check file type and size
            y = (x + j) % len(images)
            image_link = images[y]
            extension = image_link.split(".")[-1]
            logger.info("extension: " + str(extension))
            statInfo = os.stat(image_link)
            logger.info("size: " + str(statInfo.st_size))
            if (
                extension.lower() in valid_image_extensions
                and statInfo.st_size < 4000000  # keep files less than 4mb
            ):
                logger.info("found one!")
                break
            elif y == prevJ:
                raise GenericError("No Valid Images Found", code=999)

        database.hset(f"channel:{str(ctx.channel.id)}", "prevJ", str(j))
    else:
        raise GenericError("No Images Found", code=100)

    return [image_link, extension]


async def get_files(item, retries=0):
    """Returns a list of image/song filenames.

    This function also does cache management,
    looking for files in the cache for media and
    downloading images to the cache if not found.

    `item` (str) - item to get image of\n
    `retries` (int) - number of attempts completed\n
    """
    logger.info(f"get_files retries: {retries}")
    item = str(item).lower()
    category = get_category(item)
    directory = f"github_download/{category}/{item}/"
    try:
        logger.info("trying")
        files_dir = os.listdir(directory)
        logger.info(directory)
        if len(files_dir) == 0:
            raise GenericError("No Files", code=100)
        return [f"{directory}{path}" for path in files_dir]
    except (FileNotFoundError, GenericError):
        # if not found, fetch images
        logger.info("fetching files")
        logger.info("item: " + str(item))
        if retries < 3:
            await download_github()
            retries += 1
            return await get_files(item, retries)
        else:
            logger.info("More than 3 retries")
            return []


async def download_github():
    logger.info("syncing github")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    loop = asyncio.get_event_loop()
    try:
        os.listdir(f"{config.options['download_dir']}/")
    except FileNotFoundError:
        logger.info("doesn't exist, cloning")
        await loop.run_in_executor(executor, _clone)
        logger.info("done cloning")
    else:
        logger.info("exists, pulling")
        await loop.run_in_executor(executor, _pull)
        logger.info("done pulling")


def _clone():
    Repo.clone_from(config.options["github_image_repo_url"], f"{config.options['download_dir']}/")


def _pull():
    Repo(f"{config.options['download_dir']}/").remote("origin").pull()