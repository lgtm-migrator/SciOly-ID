import json
import os
import random
import shutil
import time
from typing import Callable, Union

from celery.utils.log import get_task_logger

import sciolyid.config as config
from sciolyid.data import get_category
from sciolyid.web.functions.images import filename_lookup
from sciolyid.web.git import image_repo, verify_repo
from sciolyid.web.tasks import celery_app, database

logger = get_task_logger(__name__)

GIT_PUSHINFO_FLAGS = (
    "ERROR",  # 1024
    "UP_TO_DATE",  # 512
    "FAST_FORWARD",  # 256
    "FORCED_UPDATE",  # 128
    "DELETED",  # 64
    "REMOTE_FAILURE",  # 32
    "REMOTE_REJECTED",  # 16
    "REJECTED",  # 8
    "NO_MATCH",  # 4
    "NEW_HEAD",  # 2
    "NEW_TAG",  # 1
)
GIT_PUSH_OPCODES = (
    "CHECKING_OUT",  # 256
    "FINDING_SOURCES",  # 128
    "RESOLVING",  # 64
    "RECEIVING",  # 32
    "WRITING",  # 16
    "COMPRESSING",  # 8
    "COUNTING",  # 4
    "END",  # 2
    "BEGIN",  # 1
)


def _push_helper(repo, commit_message, progress=None):
    repo.remote("origin").pull()
    index = repo.index
    index.add("*")
    index.commit(commit_message)
    push_result = repo.remote("origin").push(progress=progress)
    if len(push_result) == 0:
        return None
    set_flags = []
    for i, flag in enumerate(f"{push_result[0].flags:0>11b}"):
        if int(flag):
            set_flags.append(GIT_PUSHINFO_FLAGS[i])
    logger.info(set_flags)
    return set_flags


@celery_app.task
def push(commit_message: str, user_id: Union[int, str]):
    logger.info("pushing!")
    result = _push_helper(verify_repo, commit_message, progress=gen_progress(user_id))
    if result is None:
        database.hset(
            f"sciolyid.upload.status:{user_id}",
            mapping={"status": json.dumps(["FAIL"]), "end": int(time.time())},
        )
        logger.error("push operation failed completely!")
    else:
        database.hset(
            f"sciolyid.upload.status:{user_id}",
            mapping={"status": json.dumps(result), "end": int(time.time())},
        )
    database.delete(f"sciolyid.upload.save:{user_id}")
    database.expire(f"sciolyid.upload.status:{user_id}", 60)


def gen_progress(user_id: Union[int, str]) -> Callable:
    if isinstance(user_id, int):
        user_id = str(user_id)

    def wrapped_progress(op_code, cur_count, max_count=None, message=""):
        nonlocal user_id
        readable_opcode = {
            GIT_PUSH_OPCODES[i] if int(code) else None
            for i, code in enumerate(f"{op_code:0>9b}")
        }
        readable_opcode.discard(None)
        data = {
            "op_code": json.dumps(list(readable_opcode)),
            "cur_count": json.dumps(cur_count),
            "max_count": json.dumps(max_count),
            "message": json.dumps(message),
        }
        database.hset(f"sciolyid.upload.status:{user_id}", mapping=data)
        if (
            random.randint(1, 4) == 1  # 25%
            or "BEGIN" in readable_opcode
            or "END" in readable_opcode
        ):
            # only log occasionally
            logger.info(data)

    return wrapped_progress


@celery_app.task
def move_images():
    logger.info("checking for move")
    root = os.path.abspath(
        config.options["validation_local_dir"] + config.options["validation_repo_dir"]
    )
    lookup = filename_lookup(root)
    delete = set(
        map(
            lambda x: x.decode("utf-8"),
            database.zrangebyscore("sciolyid.verify.images:invalid", 3, "+inf")
            + database.zrangebyscore("sciolyid.verify.images:duplicate", 3, "+inf"),
        )
    )
    if delete:
        database.zremrangebyscore("sciolyid.verify.images:invalid", 3, "+inf")
        database.zremrangebyscore("sciolyid.verify.images:duplicate", 3, "+inf")
        for image in delete:
            os.remove(lookup[image])

    valid = set(
        map(
            lambda x: x.decode("utf-8"),
            database.zrangebyscore("sciolyid.verify.images:valid", 3, "+inf"),
        )
    )
    if valid:
        database.zremrangebyscore("sciolyid.verify.images:valid", 3, "+inf")
        for image in valid:
            if image in delete:
                continue
            path = lookup[image]
            item = os.path.dirname(os.path.relpath(path, root))
            category = get_category(item)
            shutil.copy(path, os.path.join(image_repo.working_tree_dir, category))
            os.remove(path)

    if valid or delete:
        verify_push = _push_helper(verify_repo, "Update through verification!")
        image_push = _push_helper(image_repo, "Update through verification!")

        for result in (("verify repo", verify_push), ("image repo", image_push)):
            if result[1] is None:
                logger.info(result[0] + " failed completely!")
            else:
                logger.info(result[0] + " push success!")
    else:
        logger.info("no changes to update!")
