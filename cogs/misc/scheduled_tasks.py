import threading
import functools
import schedule
from datetime import datetime, timedelta
from os.path import exists
import tzlocal
import shutil
import time
import pytz
from json import JSONDecodeError
import sys
import os
from pathlib import Path
from tinydb import TinyDB, Query
from cogs.misc.logger import get_logger, get_misc, get_home
from cogs.handlers.events import stop_event

LOGGER = get_logger()
HOME_PATH = get_home()
# pip install: tinydb schedule tzlocal pytz

def run_continuously(interval=60):
    class ScheduleThread(threading.Thread):
        @classmethod
        def run(cls):
            while not stop_event.is_set():
                schedule.run_pending()
                for _ in range(interval):
                    if stop_event.is_set():
                        LOGGER.info("Stopping scheduled tasks")
                        break
                    time.sleep(1)

    continuous_thread = ScheduleThread()
    continuous_thread.start()


def catch_exceptions(cancel_on_failure=False):
    def catch_exceptions_decorator(job_func):
        @functools.wraps(job_func)
        def wrapper(*args, **kwargs):
            try:
                return job_func(*args, **kwargs)
            except JSONDecodeError:
                LOGGER.error('Json Decode Error. Clearing DB...')
                clear_db()  # calling the clear_db function to clear the DB
                if cancel_on_failure:
                    return schedule.CancelJob
            except Exception:
                import traceback
                LOGGER.error(traceback.format_exc())
                if cancel_on_failure:
                    return schedule.CancelJob
        return wrapper
    return catch_exceptions_decorator

def clear_db():
    try:
        with open(HOME_PATH / "cogs" / "db" / "stats.json", 'w') as db_file:
            db_file.write('')
        LOGGER.info('DB cleared successfully.')
    except Exception as e:
        LOGGER.error(f'Failed to clear DB: {str(e)}')

class HonfiguratorSchedule():
    def __init__(self, config):
        self.config = config
        self.db = TinyDB(HOME_PATH / "cogs" / "db" / "stats.json")
        self.lock = threading.Lock() # Create a lock
        self.replay_table = self.db.table('stats_replay_count')
        self.file_deletion_table =  self.db.table('file_deletion_table')

        self.replay_cleaner_active = self.config['application_data']['timers']['replay_cleaner']['active']
        self.move_replays_to_longerm_storage = config["application_data"]["longterm_storage"]["active"]

        self.path_to_replays_locally = config["hon_data"]["hon_replays_directory"]
        self.longterm_storage_replay_path = self.config["application_data"]["longterm_storage"]["location"]
        self.active_replay_path = Path(self.longterm_storage_replay_path) if self.move_replays_to_longerm_storage else self.path_to_replays_locally #   The "active replays path" is set to local (hon_replays_directory) if there is no long term storage configured. Otherwise, it's set to long term storage location.
        self.max_replay_age_days = self.config['application_data']['timers']['replay_cleaner']["max_replay_age_days"]
        self.max_temp_files_age_days = self.config['application_data']['timers']['replay_cleaner']["max_temp_files_age_days"]
        self.max_temp_folders_age_days = self.config['application_data']['timers']['replay_cleaner']["max_temp_folders_age_days"]
        self.max_clog_age_days = self.config['application_data']['timers']['replay_cleaner']["max_clog_age_days"]

    def setup_tasks(self):
        # schedule.every(1).minutes.do(self.get_replays) #TODO: to be removed
        LOGGER.info("Setting up background jobs")
        self.cease_continuous_run = run_continuously()

        """
            Set a schedule for the tasks. The "get_replays" task has been scheduled 1 hour after replays are moved.
            It makes more sense to count the replays after they're cleaned up.
            It also gives ample time for replays to be moved. It may take up to an hour the first time, considering some of the larger server farms.
            Scheduled times are also configurable via the configuration file.
        """
        get_replays_scheduled_time_str = self.config['application_data']['timers']['replay_cleaner']['scheduled_time']
        get_replays_scheduled_time = datetime.strptime(get_replays_scheduled_time_str, "%H:%M")

        get_replaysnew_scheduled_time = get_replays_scheduled_time + timedelta(hours=1)
        get_replaysnew_scheduled_time_str = get_replaysnew_scheduled_time.strftime("%H:%M")

        schedule.every().day.at(get_replaysnew_scheduled_time_str, pytz.timezone(f"{tzlocal.get_localzone_name()}")).do(self.get_replays)
        schedule.every().day.at(self.config['application_data']['timers']['replay_cleaner']['scheduled_time'], pytz.timezone(f"{tzlocal.get_localzone_name()}")).do(self.delete_or_move_files)
        LOGGER.info("Success!")

    def stop(self):
        LOGGER.info("Stop signal for background jobs received")
        self.cease_continuous_run.set()

    @catch_exceptions()
    def get_replays(self):
        instance = Stats(self.config)
        instance.count_replays()

    @catch_exceptions()
    def delete_or_move_files(self):
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

        size_in_mb = 0
        count = 0
        for filename in os.listdir(self.active_replay_path):
            if filename.endswith(".honreplay"):
                file_path = os.path.join(self.active_replay_path, filename)
                modified_time = os.path.getmtime(file_path)
                if modified_time > yesterday:
                    size_in_mb += Path(file_path).stat().st_size  / 1000
                    count += 1
        with self.lock: # Acquire the lock before writing to the database
            self.replay_table.insert({"date" : formatted_date_str, "count" : count, "size_in_mb" : size_in_mb})


class ReplayCleaner(HonfiguratorSchedule):
    def __init__(self, config):
        super().__init__(config)

    def delete(self, file_path, method):
        if method == "file":
            file_path.unlink()
        elif method == "folder":
            shutil.rmtree(file_path)
        else:
            pass

    def delete_old_replays(self):
        counter = 0
        if self.max_replay_age_days == 0:
            return counter
        for file_path in self.active_replay_path.glob("**/*.honreplay"):
            if time.time() - file_path.stat().st_mtime > self.max_replay_age_days * 86400:
                counter += 1
                self.delete(file_path, method = "file")
        return counter

    def delete_old_tmp_files(self):
        counter = 0
        if self.max_temp_files_age_days == 0:
            return counter
        for file_path in self.path_to_replays_locally.glob("**/*.tmp"):
            if time.time() - file_path.stat().st_mtime > self.max_temp_files_age_days * 86400:
                counter += 1
                self.delete(file_path, method = "file")
        return counter

    def delete_old_folders(self):
        counter = 0
        if self.max_temp_folders_age_days == 0:
            return counter
        for folder_path in self.path_to_replays_locally.glob("*/"):
            if folder_path.is_dir() and time.time() - folder_path.stat().st_mtime > self.max_temp_folders_age_days * 86400:
                counter += 1
                self.delete(folder_path, method = "folder")
        return counter

    def delete_clog_files(self):
        counter = 0
        #TODO not implemented yet.
        return counter
    
    def move_files_to_longterm_storage(self):
        success = 0
        fail = 0
        for file_path in self.path_to_replays_locally.glob("**/*.honreplay"):
            if time.time() - file_path.stat().st_mtime > 86400:
                try:
                    shutil.move(file_path, self.longterm_storage_replay_path)
                    success += 1
                except FileExistsError:
                    try:
                        os.remove(file_path)
                    except:
                        pass
                except Exception as e:
                    LOGGER.error(f"Error moving replay file: {file_path}. {e}")
                    fail+=1
        return success,fail

    def clean(self):
        stats = {}
        if self.max_temp_files_age_days > 0:
            stats["deleted_temp_files"] = self.delete_old_tmp_files()
        else:
            stats["deleted_temp_files"] = 0

        if self.max_temp_folders_age_days > 0:
            stats["deleted_temp_folders"] = self.delete_old_folders()
        else:
            stats["deleted_temp_folders"] =  0
        
        if self.move_replays_to_longerm_storage:
            moved, failed = self.move_files_to_longterm_storage()
            stats["moved_replays"] = moved
            stats["failed_to_move_replays"] = failed
        else:
            stats["moved_replays"] = 0

        if self.max_clog_age_days > 0:
            stats["clog_files"] = self.delete_clog_files()
        else:
            stats["clog_files"] = 0

        if self.max_replay_age_days > 0 and self.replay_cleaner_active:
            stats["deleted_replays"] = self.delete_old_replays()
        else:
            stats["deleted_replays"] = 0
        
        stats["date"] = datetime.now().strftime("%Y-%m-%d")
        
        with self.lock: # Acquire the lock before writing to the database
            self.file_deletion_table.insert(stats)

class FileRelocator(HonfiguratorSchedule):
    def __init__(self, config):
        super().__init__(config)
    
