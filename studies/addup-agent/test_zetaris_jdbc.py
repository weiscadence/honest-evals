"""One-shot test: live JDBC query against the local Zetaris instance on the Mac.

What it proves: the agent can query Zetaris live (not just the UI) and run the
add-up itself. If this prints the 4 rows, the live call is real and we wire it
into addup/zetaris.py as a jdbc mode.

Run on the Mac, in Terminal, from the folder where you save this file:
  1. java -version            (need a JVM; if this errors, install one first:
                               brew install openjdk)
  2. pip3 install JayDeBeApi
  3. python3 test_zetaris_jdbc.py [path/to/ndp-jdbc-driver-*.jar]

The jar: from gateway step 8, file ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar.
If you don't pass a path, the script looks in ~/Downloads for it.

Credentials: user/password come from gateway step 7. Set them as env vars:
  ZETARIS_JDBC_USER=... ZETARIS_JDBC_PASSWORD=... python3 test_zetaris_jdbc.py
If step 7 is unclear, it first tries the UI login (admin@zetaris.com / admin).
If no password is given, the script prompts for it (hidden input, never stored
or written to shell history). The password is deliberately NOT in this file:
the script is shared via a public drop and a public repo.
"""
import getpass
import glob
import os
import sys

import jaydebeapi

DRIVER = "com.zetaris.lightning.jdbc.LightningDriver"
URL = "jdbc:zetaris:lightning@localhost:10000"

# Find the jar: arg wins, else ~/Downloads.
if len(sys.argv) > 1:
    jar = os.path.expanduser(sys.argv[1])
else:
    found = sorted(glob.glob(os.path.expanduser("~/Downloads/ndp-jdbc-driver-*.jar")))
    if not found:
        print("NO JAR FOUND. Find ndp-jdbc-driver-*.jar (gateway step 8 download) and run:")
        print("  python3 test_zetaris_jdbc.py /path/to/ndp-jdbc-driver-*.jar")
        sys.exit(2)
    jar = found[0]
print("jar:", jar)

user = os.environ.get("ZETARIS_JDBC_USER", "admin@zetaris.com")
password = os.environ.get("ZETARIS_JDBC_PASSWORD")
if not password:
    password = getpass.getpass("Zetaris JDBC password (from gateway step 7): ")

conn = jaydebeapi.connect(DRIVER, URL, [user, password], jar)
cur = conn.cursor()
cur.execute("SELECT 1")
print("SELECT 1 ->", cur.fetchall())
cur.execute(
    "SELECT episode, payee, SUM(amount) AS team_total "
    "FROM addup.addup_payments WHERE status = 'paid' GROUP BY episode, payee"
)
rows = cur.fetchall()
for row in rows:
    print(row)
print("rows:", len(rows))
cur.close()
conn.close()
print("LIVE ZETARIS JDBC: OK")
