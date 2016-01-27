download-hamish-and-andy
========================

A script to download Hamish and Andy podcasts from handa.libsyn.com
```
--page        page number to begin downloading from
--limit       maximum number of episodes to download
--offset      number of episodes to skip
--page-limit  maximum number of pages to download
--username    username for my.libsyn.com (only required for premium eps)
--password    password for my.libsyn.com (only required for premium eps)
--dry-run     just test things out
```

Requires python3, mechanicalsoup and eyed3 (you'll need to clone master and install manually, 0.7.8 doesn't support python3)
