import threading
import schedule
import datetime
import tzlocal
import shutil
import time
import pytz
import sys
import os
from pathlib import Path
from tinydb import TinyDB, Query

# pip install: tinydb schedule tzlocal pytz

def run_continuously(interval=60):
    cease_continuous_run = threading.Event()
    class ScheduleThread(threading.Thread):
        @classmethod
        def run(cls):
            while not cease_continuous_run.is_set():
                schedule.run_pending()
                time.sleep(interval) # execute every minute (for now..)

    continuous_thread = ScheduleThread()
    continuous_thread.start()
    return cease_continuous_run


class HonfiguratorSchedule():
    def __init__(self, config):
        self.config = config
        self.replay_dir = config["hon_data"]["hon_replays_directory"]
        self.db = TinyDB("stats.json")
        self.replay_table = self.db.table('stats_replay_count')
        self.file_deletion_table =  self.db.table('file_deletion_table')

        self.path_to_replays = self.config["hon_data"]["hon_replays_directory"]
        self.max_replay_age_days = self.config['application_data']['timers']['replay_cleaner']["max_replay_age_days"]
        self.max_temp_files_age_days = self.config['application_data']['timers']['replay_cleaner']["max_temp_files_age_days"]
        self.max_temp_folders_age_days = self.config['application_data']['timers']['replay_cleaner']["max_temp_folders_age_days"]
        self.max_clog_age_days = self.config['application_data']['timers']['replay_cleaner']["max_clog_age_days"]
        self.now = time.time()

    def setup_tasks(self):
        # schedule.every(1).minutes.do(self.get_replays) #TODO: to be removed
        self.cease_continuous_run = run_continously()
        schedule.every().day.at("01:00", pytz.timezone(f"{tzlocal.get_localzone_name()}")).do(self.get_replays)
        schedule.every().day.at("01:10", pytz.timezone(f"{tzlocal.get_localzone_name()}")).do(self.delete_files)

    def stop(self):
        self.cease_continuous_run.set()

    def get_replays(self):
        instance = Stats(self.config)
        instance.count_replays()

    def delete_files(self):
        #if replay_config.get("active") == True:
        instance = ReplayCleaner(self.config)
        instance.clean()


class Stats(HonfiguratorSchedule):
    def __init__(self, config):
        super().__init__(config)

    def count_replays(self):
        yesterday = time.time() - 24 * 60 * 60  # subtract 24 hours in seconds
        time_obj = time.gmtime(yesterday)
        year_str = time.strftime("%Y", time_obj)
        month_str = time.strftime("%m", time_obj)
        day_str = time.strftime("%d", time_obj).lstrip("0")
        formatted_date_str = f"{year_str}-{month_str}-{day_str}"

        count = 0
        for filename in os.listdir(self.replay_dir):
            if filename.endswith(".honreplay"):
                file_path = os.path.join(self.replay_dir, filename)
                modified_time = os.path.getmtime(file_path)
                if modified_time > yesterday:
                    count += 1
        self.replay_table.insert({"date" : formatted_date_str, "count" : count})


class ReplayCleaner(HonfiguratorSchedule):
    def __init__(self, config):
        super().__init__(config)

    def delete(self, file_path, method):
        if method == "file":
            #file_path.unlink()
            pass
        elif method == "folder":
            #shutil.rmtree(file_path)
            pass
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
        if self.max_temp_files_age_days == 0:
            return counter
        for file_path in self.path_to_replays.glob("**/*.tmp"):
            if self.now - file_path.stat().st_mtime > self.max_temp_files_age_days * 86400:
                counter += 1
                self.delete(file_path, method = "file")
        return counter

    def delete_old_folders(self):
        counter = 0
        if self.max_temp_folders_age_days == 0:
            return counter
        for folder_path in self.path_to_replays.glob("*/"):
            if folder_path.is_dir() and self.now - folder_path.stat().st_mtime > self.max_temp_folders_age_days * 86400:
                counter += 1
                self.delete(folder_path, method = "folder")
        return counter

    def delete_clog_files(self):
        counter = 0
        #TODO not implemented yet.
        return counter

    def clean(self):
        stats = {}
        if self.max_replay_age_days > 0:
            stats["deleted_replays"] = self.delete_old_replays()
        else:
            stats["deleted_replays"] = 0

        if self.max_temp_files_age_days > 0:
            stats["deleted_temp_files"] = self.delete_old_tmp_files()
        else:
            stats["deleted_temp_files"] = 0

        if self.max_temp_folders_age_days > 0:
            stats["deleted_temp_folders"] = self.delete_old_folders()
        else:
            stats["deleted_temp_folders"] =  0

        if self.max_clog_age_days > 0:
            stats["clog_files"] = self.delete_clog_files()
        else:
            stats["clog_files"] = 0

        self.file_deletion_table.insert(stats)
