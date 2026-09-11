import argparse
import os
from dotenv import load_dotenv
from database import Database

load_dotenv()
db = Database(os.getenv("DB_PATH", "data/bot.sqlite3"))
db.init()

p = argparse.ArgumentParser(description="Manage verified users")
sub = p.add_subparsers(dest="cmd", required=True)

v = sub.add_parser("verify")
v.add_argument("user_id", type=int)
v.add_argument("--name", default="")
v.add_argument("--username", default="")

u = sub.add_parser("unverify")
u.add_argument("user_id", type=int)

sub.add_parser("list")

args = p.parse_args()

if args.cmd == "verify":
    db.add_verified(args.user_id, args.name, args.username)
    print(f"Verified: {args.user_id}")
elif args.cmd == "unverify":
    db.remove_verified(args.user_id)
    print(f"Unverified: {args.user_id}")
elif args.cmd == "list":
    for row in db.list_verified(100000):
        print(row["user_id"], row["name"], row["username"])
