#!/usr/bin/env python3
import os
import sys
import shutil
import time
from pathlib import Path

class ReplayCleaner:
    def __init__(self, path_to_replays, max_replay_age_days=14, max_tmp_age_days=1, max_folder_age_days=1):
        self.path_to_replays = Path(path_to_replays)
        self.max_replay_age_days = max_replay_age_days
        self.max_tmp_age_days = max_tmp_age_days
        self.max_folder_age_days = max_folder_age_days
        self.now = time.time()

    def delete(self, file_path, method):
        if method == "file":
            file_path.unlink()
            print(f"Delete old file: {file_path}")
        elif method == "folder":
            shutil.rmtree(file_path)
            print(f"Delete old folder: {file_path}")
        else:
            pass

    def delete_old_replays(self):
        counter = 0
        if self.max_replay_age_days == 0:
            return counter
        for file_path in self.path_to_replays.glob("**/*.honreplay"):
            if self.now - file_path.stat().st_mtime > self.max_replay_age_days * 86400:
                counter += 1
                self.delete(file_path, method = "file")
        return counter

    def delete_old_tmp_files(self):
        counter = 0
        if self.max_tmp_age_days == 0:
            return counter
        for file_path in self.path_to_replays.glob("**/*.tmp"):
            if self.now - file_path.stat().st_mtime > self.max_tmp_age_days * 86400:
                counter += 1
                self.delete(file_path, method = "file")
        return counter

    def delete_old_folders(self):
        counter = 0
        if self.max_folder_age_days == 0:
            return counter
        for folder_path in self.path_to_replays.glob("*/"):
            if folder_path.is_dir() and self.now - folder_path.stat().st_mtime > self.max_folder_age_days * 86400:
                counter += 1
                self.delete(folder_path, method = "folder")
        return counter

    def clean(self):
        stats = {}
        stats["deleted_replays"] = self.delete_old_replays()
        stats["deleted_temp_files"] = self.delete_old_tmp_files()
        stats["deleted_temp_folders"] = self.delete_old_folders()
        return stats

if __name__ == "__main__":
    if sys.platform == "win32":
        PATH_TO_REPLAYS = "C:/opt/hon/config/game/replays/"
    else:
        PATH_TO_REPLAYS = "/opt/hon/config/game/replays/"
    cleaner = ReplayCleaner(PATH_TO_REPLAYS)
    #MAX_REPLAY_AGE_DAYS = int(input(f"Enter max age (in days) for replay files (default {cleaner.max_replay_age_days}): ") or cleaner.max_replay_age_days)
    #MAX_TMP_AGE_DAYS = int(input(f"Enter max age (in days) for tmp files (default {cleaner.max_tmp_age_days}): ") or cleaner.max_tmp_age_days)
    #MAX_FOLDER_AGE_DAYS = int(input(f"Enter max age (in days) for folders (default {cleaner.max_folder_age_days}): ") or cleaner.max_folder_age_days)
    MAX_REPLAY_AGE_DAYS = cleaner.max_replay_age_days
    MAX_TMP_AGE_DAYS = cleaner.max_tmp_age_days
    MAX_FOLDER_AGE_DAYS = cleaner.max_folder_age_days
    cleaner = ReplayCleaner(PATH_TO_REPLAYS, MAX_REPLAY_AGE_DAYS, MAX_TMP_AGE_DAYS, MAX_FOLDER_AGE_DAYS)
    print(cleaner.clean())
