# functions.py | function definitions
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

import difflib
import math
import os
import string
from io import BytesIO

from PIL import Image

import sciolyid.config as config
from sciolyid.data import database, groups, id_list, logger

async def channel_setup(ctx):
    """Sets up a new discord channel.
    
    `ctx` - Discord context object
    """
    logger.info("checking channel setup")
    if database.exists(f"channel:{ctx.channel.id}"):
        logger.info("channel data ok")
    else:
        database.hmset(
            f"channel:{ctx.channel.id}",
            {
                "item": "",
                "answered": 1,
                "prevJ": 20,
                "prevI": ""
            },
        )
        # true = 1, false = 0, prevJ is 20 to define as integer
        logger.info("channel data added")
        await ctx.send("Ok, setup! I'm all ready to use!")

async def user_setup(ctx):
    """Sets up a new discord user for score tracking.
    
    `ctx` - Discord context object
    """
    logger.info("checking user data")
    if database.zscore("users:global", str(ctx.author.id)) is not None:
        logger.info("user global ok")
    else:
        database.zadd("users:global", {str(ctx.author.id): 0})
        logger.info("user global added")
        await ctx.send("Welcome <@" + str(ctx.author.id) + ">!")

    # Add streak
    if (database.zscore("streak:global", str(ctx.author.id)) is
        not None) and (database.zscore("streak.max:global", str(ctx.author.id)) is not None):
        logger.info("user streak in already")
    else:
        database.zadd("streak:global", {str(ctx.author.id): 0})
        database.zadd("streak.max:global", {str(ctx.author.id): 0})
        logger.info("added streak")

    if ctx.guild is not None:
        logger.info("no dm")
        if database.zscore(f"users.server:{ctx.guild.id}", str(ctx.author.id)) is not None:
            server_score = database.zscore(f"users.server:{ctx.guild.id}", str(ctx.author.id))
            global_score = database.zscore("users:global", str(ctx.author.id))
            if server_score is global_score:
                logger.info("user server ok")
            else:
                database.zadd(f"users.server:{ctx.guild.id}", {str(ctx.author.id): global_score})
        else:
            score = int(database.zscore("users:global", str(ctx.author.id)))
            database.zadd(f"users.server:{ctx.guild.id}", {str(ctx.author.id): score})
            logger.info("user server added")
    else:
        logger.info("dm context")

async def item_setup(ctx, item: str):
    """Sets up a new item for incorrect tracking.
    
    `ctx` - Discord context object
    `item` - item to setup
    """
    logger.info("checking item data")
    if database.zscore("incorrect:global", string.capwords(item)) is not None:
        logger.info("item global ok")
    else:
        database.zadd("incorrect:global", {string.capwords(item): 0})
        logger.info("item global added")

    if database.zscore(f"incorrect.user:{ctx.author.id}", string.capwords(item)) is not None:
        logger.info("item user ok")
    else:
        database.zadd(f"incorrect.user:{ctx.author.id}", {string.capwords(item): 0})
        logger.info("item user added")

    if ctx.guild is not None:
        logger.info("no dm")
        if database.zscore(f"incorrect.server:{ctx.guild.id}", string.capwords(item)) is not None:
            logger.info("item server ok")
        else:
            database.zadd(f"incorrect.server:{ctx.guild.id}", {string.capwords(item): 0})
            logger.info("item server added")
    else:
        logger.info("dm context")

    if database.exists(f"session.data:{ctx.author.id}"):
        logger.info("session in session")
        if database.zscore(f"session.incorrect:{ctx.author.id}", string.capwords(item)) is not None:
            logger.info("item session ok")
        else:
            database.zadd(f"session.incorrect:{ctx.author.id}", {string.capwords(item): 0})
            logger.info("item session added")
    else:
        logger.info("no session")

def error_skip(ctx):
    """Skips the current item.
    
    Passed to send_image() as on_error to skip the item when an error occurs to prevent error loops.
    """
    logger.info("ok")
    database.hset(f"channel:{ctx.channel.id}", "item", "")
    database.hset(f"channel:{ctx.channel.id}", "answered", "1")

def session_increment(ctx, item: str, amount: int = 1):
    """Increments the value of a database hash field by `amount`.

    `ctx` - Discord context object\n
    `item` - hash field to increment (see data.py for details,
    possible values include correct, incorrect, total)\n
    `amount` (int) - amount to increment by, usually 1
    """
    logger.info(f"incrementing {item} by {amount}")
    value = int(database.hget(f"session.data:{ctx.author.id}", item))
    value += int(amount)
    database.hset(f"session.data:{ctx.author.id}", item, str(value))

def incorrect_increment(ctx, item: str, amount: int = 1):
    """Increments the value of an incorrect item by `amount`.

    `ctx` - Discord context object\n
    `item` - item that was incorrect\n
    `amount` (int) - amount to increment by, usually 1
    """
    logger.info(f"incrementing incorrect {item} by {amount}")
    database.zincrby("incorrect:global", amount, string.capwords(item))
    database.zincrby(f"incorrect.user:{ctx.author.id}", amount, string.capwords(item))
    if ctx.guild is not None:
        logger.info("no dm")
        database.zincrby(f"incorrect.server:{ctx.guild.id}", amount, string.capwords(item))
    else:
        logger.info("dm context")
    if database.exists(f"session.data:{ctx.author.id}"):
        logger.info("session in session")
        database.zincrby(f"session.incorrect:{ctx.author.id}", amount, string.capwords(item))
    else:
        logger.info("no session")

def score_increment(ctx, amount: int = 1):
    """Increments the score of a user by `amount`.

    `ctx` - Discord context object\n
    `amount` (int) - amount to increment by, usually 1
    """
    logger.info(f"incrementing score by {amount}")
    database.zincrby("score:global", amount, str(ctx.channel.id))
    database.zincrby("users:global", amount, str(ctx.author.id))

def black_and_white(input_image_path) -> BytesIO:
    """Returns a black and white version of an image.

    Output type is a file object (BytesIO).

    `input_image_path` - path to image (string) or file object
    """
    logger.info("black and white")
    with Image.open(input_image_path) as color_image:
        bw = color_image.convert("L")
        final_buffer = BytesIO()
        bw.save(final_buffer, "png")
    final_buffer.seek(0)
    return final_buffer

def build_id_list(group_str: str = ""):
    categories = group_str.split(" ")

    id_choices = []
    category_output = ""

    if not config.options["id_groups"]:
        return (id_list, "None")

    group_args = set(groups.keys()).intersection({category.lower() for category in categories})
    category_output = " ".join(group_args).strip()
    for group in group_args:
        id_choices += groups[group]

    if not id_choices:
        id_choices += id_list
        category_output = "None"

    return (id_choices, category_output.strip())

def owner_check(ctx) -> bool:
    """Check to see if the user is the owner of the bot."""
    owners = set(str(os.getenv("ids")).split(","))
    return str(ctx.author.id) in owners

def spellcheck_list(word_to_check, correct_list, abs_cutoff=None):
    for correct_word in correct_list:
        if abs_cutoff is None:
            relative_cutoff = math.floor(len(correct_word) / 3)
        if spellcheck(word_to_check, correct_word, relative_cutoff) is True:
            return True
    return False

def spellcheck(worda, wordb, cutoff=3):
    """Checks if two words are close to each other.
    
    `worda` (str) - first word to compare
    `wordb` (str) - second word to compare
    `cutoff` (int) - allowed difference amount
    """
    worda = worda.lower()
    wordb = wordb.lower()
    shorterword = min(worda, wordb, key=len)
    if worda != wordb:
        if len(list(difflib.Differ().compare(worda, wordb))) - len(shorterword) >= cutoff:
            return False
    return True
