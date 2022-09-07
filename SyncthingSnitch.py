#!/usr/bin/env python3
"""
Module Docstring
"""

__author__ = "Marcel Keßler"
__version__ = "0.2"

import argparse
import requests
import mimetypes

import telegram
from logzero import logger
from time import sleep
from telegram import Bot
from os.path import exists, basename


def debug_msg(msg, args):
    if args.verbose > 0:
        logger.debug(msg)


def fetch_events(args, last_id):
    headers = {"X-API-Key": args.auth}
    proto = "http://"
    if args.ssl:
        proto = "https://"
    url = (
        proto
        + args.host
        + "/rest/events/disk"
        + "?since="
        + str(last_id)
        + "&timeout="
        + str(args.timeout)
    )
    debug_msg("Used url: '%s'" % url, args)
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.info("Error while fetching events. Gonna try again...")
            sleep(args.timeout)
            return None
    except requests.RequestException:
        logger.info("Error while fetching events. Gonna try again...")
        sleep(args.timeout)
        return None


def send_event(event, bot, args):
    msg_text = (
        "🕵️‍♂️  Meine Spürnase hat frische Ware entdeckt\! 👀\n\nLabel: `%s` \- File: `%s`"  # pyright: ignore [reportInvalidStringEscapeSequence]
        % (event["data"]["label"], basename(event["data"]["path"]))
    )
    # Send message, retry three times on error
    for _ in range(3):
        try:
            bot.sendMessage(
                chat_id=args.telegram_chat_id,
                text=msg_text,
                parse_mode=telegram.constants.PARSEMODE_MARKDOWN_V2,
            )
        except telegram.TelegramError as e:
            debug_msg("Telegram error: %s" % e, args)
            sleep(args.timeout)
            continue
        else:
            logger.info(
                "Sending event '%d' with path '%s' succeed."
                % (event["id"], event["data"]["path"])
            )
            break
    else:
        debug_msg("Sending event failed completely. Skipping...", args)


def parse_event(event, bot, args):
    # Action Type
    if event["data"]["action"] != "modified":
        debug_msg(
            "%d - Ignoring action type '%s'. Skipping ..."
            % (event["id"], event["data"]["action"]),
            args,
        )
        return event["id"]
    # Event Type
    if event["type"] != "LocalChangeDetected":
        debug_msg(
            "%d - Filtering out event type 'RemoteChangeDetected'. Skipping..."
            % event["id"],
            args,
        )
        return event["id"]
    # File Type
    if event["data"]["type"] != "file":
        debug_msg(
            "%d - Filtering out non file type events. Skipping..." % event["id"], args
        )
        return event["id"]
    # Folder Label
    if args.label is not None:
        if not event["data"]["label"] in args.label:
            debug_msg(
                "%d - Label '%s' not in provided list '%s'. Skipping..."
                % (event["id"], event["data"]["label"], args.label),
                args,
            )
            return event["id"]
    # Movie Filter
    if args.filter_movies:
        event_mimetype = mimetypes.guess_type(event["data"]["path"])
        if event_mimetype[0] is None:
            # Mimetype not detectable. Skipping...
            debug_msg(
                "%d - Mimetype of '%s' not detectable. Skipping..."
                % (event["id"], event["data"]["type"]),
                args,
            )
            return event["id"]
        if not event_mimetype[0].startswith("video"):
            debug_msg(
                "%d - Path '%s' doesn't match video file type. Skipping..."
                % (event["id"], event["data"]["type"]),
                args,
            )
            return event["id"]
    # Filter Samples
    if "sample" in event["data"]["path"] or "Sample" in event["data"]["path"]:
        debug_msg(
            "%d - Path '%s' contains 'Sample'. Skipping..."
            % (event["id"], event["data"]["path"]),
            args,
        )
        return event["id"]
    # Send update
    send_event(event, bot, args)
    return event["id"]


def main(args):
    """Main entry point of the app"""
    # Print arguments
    debug_msg(f"Arguments: %s" % args, args)
    # Starting Bot
    bot = Bot(args.telegram_bot_token)
    # Set/Read last_id
    last_id = 0
    if exists(args.id_file_location):
        f = open(args.id_file_location, "r")
        last_id = int(f.read())
        debug_msg(
            "Found last_id '%d' in file '%s'." % (last_id, args.id_file_location), args
        )
        f.close()

    events = fetch_events(args, last_id)
    if events is None:
        debug_msg("Error while fetching events from API. Exiting...", args)
        exit(1)

    # Loop over events, skip if event is older than last_id from file. Function parse_event send's notification
    for event in events:
        debug_msg(event, args)
        if event["id"] <= last_id:
            debug_msg(
                "Event with ID '%d' already parsed. Skipping..." % event["id"], args
            )
            continue
        last_id = parse_event(event, bot, args)

    try:
        f = open(args.id_file_location, "w")
        f.write(str(last_id))
        f.close()
    except BaseException as e:
        debug_msg("Error while writing file: %s" % e, args)
    exit(0)


if __name__ == "__main__":
    """This is executed when run from the command line"""
    parser = argparse.ArgumentParser()

    # Telegram Chat ID
    parser.add_argument(
        "-i",
        "--telegram_chat_id",
        action="store",
        required=True,
        help="Telegram chat ID to report to",
    )

    # Telegram Bot Token
    parser.add_argument(
        "-t",
        "--telegram_bot_token",
        action="store",
        required=True,
        help="Telegram Bot token to send messages",
    )

    # Host
    parser.add_argument("-H", "--host", action="store", default="localhost")

    # Port
    parser.add_argument("-p", "--port", type=int, action="store", default=8384)

    # API-Key
    parser.add_argument(
        "-a",
        "--auth",
        action="store",
        required=True,
        help="Required Syncthing API-Key for authentication.",
    )

    # Timeout
    parser.add_argument(
        "-T",
        "--timeout",
        action="store",
        default=10,
        type=int,
        help="Time to wait if no new event exits. Also time between calls made.",
    )

    # SSL
    parser.add_argument("-s", "--ssl", action="store_true", default=False)

    # Label
    parser.add_argument(
        "-l", "--label", action="append", help="Only show events matching defined label"
    )

    # FilterMovies
    parser.add_argument(
        "--filter_movies",
        action="store_true",
        default=False,
        help="Only show events matching movie files",
    )

    # ID File Location
    parser.add_argument(
        "--id_file_location",
        action="store",
        default="./SyncthingSnitch.id",
        help="File to save last used id.",
    )

    # Optional verbosity counter (eg. -v, -vv, -vvv, etc.)
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Verbosity (-v, -vv, etc)"
    )

    # Specify output of "--version"
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (version {version})".format(version=__version__),
    )

    args = parser.parse_args()
    main(args)
