import cogs.TCP.listeners.auto_ping as udp_lsnr
import cogs.data_handler as data_handler
import subprocess
import traceback
import asyncio
import fnmatch
import shutil
import psutil
import glob
import time
import os
import re
from datetime import datetime
from threading import Thread
from os.path import exists

# processed_data_dict = dmgr.mData().returnDict()

class honCMD:
    """
        Only used for controlling HoN server instances
    """
    def __init__(self,id):
        self.id = id
        self.status = {}
    async def start_server(self):
        if await self.get_running_server():
            return

        free_mem = psutil.virtual_memory().available
        #   HoN server instances use up to 1GM RAM per instance. Check if this is free before starting.
        if free_mem > 1000000000:
            #   Server instances write files to location dependent on USERPROFILE and APPDATA variables
            os.environ["USERPROFILE"] = self.gbl_config['hon_data']['hon_home_directory']
            os.environ["APPDATA"] = self.gbl_config['hon_data']['hon_home_directory']

            DETACHED_PROCESS = 0x00000008
            params = ';'.join(' '.join((f"set {key}",str(val))) for (key,val) in self.local_config['params'].items())
            if sys.platform == "win32":
                cmdline_args = [self.local_config['config']['file_path'],"-dedicated","-noconfig","-execute",params,"-masterserver",self.gbl_config['hon_data']['master_server'],"-register","127.0.0.1:1135"]
                exe = subprocess.Popen(cmdline_args,close_fds=True, creationflags=DETACHED_PROCESS)
            else:
                cmdline_args = [self.local_config['config']['file_path'],"-cowmaster","-dedicated","-noconfig","-execute","servicecvars",params,"-masterserver",self.gbl_config['hon_data']['master_server'],"-register","127.0.0.1:1135"]
                exe = subprocess.Popen(cmdline_args,close_fds=True, start_new_session=True)
    def stop_server(self):
        return
    def schedule_stop_server(self):
        return
    def schedule_start_server(self):
        return
    def append_log_file(self,log_msg,log_lvl):
        print(f"Logging to {self.gbl_data['log_file']}")
        print(f"[{log_lvl}] {log_msg}")
    def set_server_params(self,params):
        self.params = params
    def set_server_id(self,id):
        self.id = id
    def set_local_config(self,data):
        self.local_config = data
    def set_global_config(self,data):
        self.gbl_config = data
    def set_runtime_variables(self):
        return
    def get_server_params(self):
        return self.params
    def get_server_data(self):
        return self.server_data
    def get_server_id(self):
        return self.id
    def get_current_slave_log(self):
        #   get list of files that matches pattern
        pattern=f"Slave{self.id}_M*.clog"
        files = []
        for file in os.listdir(self.gbl_config['hon_data']['hon_logs_directory']):
            if fnmatch.fnmatch(file, pattern):
                files.append(os.path.join(self.gbl_config['hon_data']['hon_logs_directory'], file))
        #   sort by modified time
        files.sort(key=lambda x: os.path.getmtime(x))
        if len(files) > 0:
            match_file = os.path.basename(files[-1])
            return match_file
        else:
            return False
    def get_current_match_time(self):
        return
    def get_current_match_id(self):
        try:
            slave_log = self.get_current_slave_log
            if not slave_log:
                # TODO: check if this does what I want it to. Initalise the match check even tho there's no match files
                # self.status.update({'initialised':True})
                return False
            matchID = re.findall(r'_(\w+)_', slave_log)
            if len(matchID) > 0:
                matchID = matchID[0]
            else: raise(f"Unable to correctly parse the match ID from the slave log file: {slave_log}")

            # hard_data = honCMD.compare_filesizes(self,match_file,"match")
            # soft_data = os.stat(match_file).st_size # initial file size

            # if 'initialised' not in self.status:
            #     self.status.update({'initialised':True})
            #     return True
            # if 'match_id' in self.status:
            #     if matchID != self.status['match_id']:
            #         print("refreshing match ID")
            #         return True
            # else: self.status.update({'match_id':matchID})
            return matchID
        except Exception:
            print(traceback.format_exc())
        return False
    def get_status_dict(self):
        return self.status
    def get_readiness(self):
        self.get_current_match_id()
        if Misc.check_port(self.local_config['params']['svr_proxyLocalVoicePort']):
            return True
        return False
    async def get_state(self):
        await self.get_running_server()
        player_count = self.get_player_count()
        state = ""
        if player_count == -3:
            return "offline"
        elif player_count == -1:
            return "starting"
        elif player_count == 0:
            if self.get_readiness():
                return "idle"
            else:
                return "starting"
        elif player_count > 0:
            return "online"
    async def get_running_server(self):
        """
            Check if existing hon server is running.
        """
        running_procs = Misc.get_proc(self.local_config['config']['file_name'])
        last_good_proc = None

        while len(running_procs) > 0:
            for proc in running_procs:
                player_count = self.get_player_count(proc.pid)
                if player_count >= 0:
                    last_good_proc = running_procs.pop()
                elif player_count < 0:
                    if not Misc.check_port(self.local_config['params']['svr_port']):
                        proc.terminate()

        if last_good_proc:
            #   update the process information with the healthy instance PID. Healthy playercount is either -3 (off) or >= 0 (alive)
            self.status.update({
                'now':f'{"idle" if player_count == 0 else "online" if player_count > 0 else "offline" if player_count < 0 else ""}',
                'player_count':player_count,
                '_pid':proc.pid,
                '_proc':proc,
                '_proc_hook':psutil.Process(pid=proc.pid),
                '_pid_owner':proc.username()
            })
            try:
                self.set_runtime_variables()
                return True
            except Exception:
                print(traceback.format_exc())
                self.append_log_file(f"{traceback.format_exc()}","WARNING")
        else:
            self.status.update({'now':'offline'})
            return False
    def get_player_count(self,*pid):
        arg1 = self.gbl_config['hon_data']['count_players_exe']
        if len(pid) > 0:
            arg2 = str(pid[0])
        else: arg2 = self.local_config["config"]["file_name"]
        check = subprocess.Popen([arg1,arg2],stdout=subprocess.PIPE, text=True)
        i = int(check.stdout.read())
        check.terminate()
        return i


class honCMD2():
    def __init__(self,server):
        #self.server = server
        #self.server_status = server_status_dict
        #server_status_dict.update({"last_restart":honCMD.getData(self,"lastRestart")})
        return
    def onerror(func, path, exc_info):
            """
            Error handler for ``shutil.rmtree``.

            If the error is due to an access error (read only file)
            it attempts to add write permission and then retries.

            If the error is for another reason it re-raises the error.

            Usage : ``shutil.rmtree(path, onerror=onerror)``
            """
            import stat
            # Is the error an access error?
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                raise
    def count_proc(proc_name):
        procs = []
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                procs.append(proc.pid)
        if len(procs) > 1:
            return procs
        else: return False
    def check_proc(proc_name):
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                return True
        return False
    def stop_proc_by_name(proc_name):
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                try:
                    proc.kill()
                except Exception as e:
                    print(e)
    def stop_proc_by_pid(proc_pid):
        for proc in psutil.process_iter():
            if proc.pid == proc_pid:
                try:
                    proc.kill()
                except Exception as e:
                    print(e)
    def check_port(port):
        command = subprocess.Popen(['netstat','-oanp','udp'],stdout=subprocess.PIPE)
        result = command.stdout.read()
        result = result.decode()
        if f"0.0.0.0:{port}" in result:
            return True
        else:
            return False
    """
    Game server updates
    """
    def check_current_match_id(self,reload,update_id_only,server,config):
        try:
            #   get list of files that matches pattern
            pattern="M*.log"
            files = list(filter(os.path.isfile,glob.glob(pattern)))
            #   sort by modified time
            files.sort(key=lambda x: os.path.getmtime(x))

            #   get last item in list
            matchLoc = files[-1]
            matchID = matchLoc.replace(".log","")

            hard_data = honCMD.compare_filesizes(self,matchLoc,"match")
            soft_data = os.stat(matchLoc).st_size # initial file size

            if update_id_only:
                return True
            if 'match_id' in match_status:
                if matchID != match_status['match_id'] or reload or (matchID == match_status['match_id'] and soft_data > hard_data and match_status['first_run'] == True):
                    #if self.server_status["bot_first_run"] == True:
                        #self.server_status.update({'bot_first_run':False})
                    print("refreshing match ID")
                    honCMD().initialise_variables("soft","soft - called by match ID refresher")
                    print(f"Lobby created. Match ID: {matchID}")
                    match_status.update({'match_id':matchID})
                    match_status.update({'first_run':False})
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Lobby created: {matchID}","INFO")
                    match_status.update({'now':"in lobby"})
                    return True
            else: match_status.update({'match_id':matchID})
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{config[0]['application_data']['log_file']}",f"{traceback.format_exc()}","WARNING")
            return False
        return False
    def count_total_games_played():
        print()
    def check_current_game_time(self):
        tempData = {}
        #
        if self.server_status["game_log_location"] == "empty":
            honCMD().get_current_game_log()
        #print("checking for game started now")

        hard_data = honCMD.compare_filesizes(self,self.server_status["game_log_location"],"game")
        soft_data = os.stat(self.server_status['game_log_location']).st_size # initial file size

        tempData = {}
        if soft_data > hard_data:
            self.server_status.update({'slave_log_checked':True})
            with open (self.server_status['game_log_location'], "r", encoding='utf-16-le') as f:
                for line in reversed(list(f)):
                    if "Server Status" in line:
                        #Match Time(00:07:00)
                        if "Match Time" in line:
                            pattern="(Match Time\()(.*)(\))"
                            try:
                                match_time=re.search(pattern,line)
                                match_time = match_time.group(2)
                                if match_time != match_status['match_time']:
                                    tempData.update({'match_time':match_time})
                                    #tempData.update({'match_log_last_line':num})
                                    self.server_status.update({'tempcount':-5})
                                    self.server_status.update({'update_embeds':True})
                                    honCMD.updateStatus_GI(self,tempData)
                                    print(f"Match in progress, elapsed duration: {match_time}")
                                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"[{match_status['match_id']}] Match in progress, elapsed duration: {match_time}","INFO")
                                break
                            except AttributeError as e:
                                print(e)
                            #if "Server Skipped" in line:
            f.close()
    def get_match_information(self):
        tempData = {}
        #if honCMD().compare_num_matches_played():
        #
        if self.server_status['match_log_location'] == "empty":
            honCMD().get_current_match_log()

        hard_data = honCMD.compare_filesizes(self,self.server_status["match_log_location"],"match")
        soft_data = os.stat(self.server_status['match_log_location']).st_size # initial file size

        if soft_data > hard_data:
            print("getting match information")
            self.server_status.update({'match_log_checked':True})
            with open (self.server_status['match_log_location'], "r", encoding='utf-16-le') as f:
                for line in f:
                    if "INFO_MATCH name:" in line:
                        game_name = re.findall(r'"([^"]*)"', line)
                        game_name = game_name[0]
                        tempData.update({'game_name':game_name})
                        honCMD.updateStatus(self,tempData)
                        honCMD.updateStatus_GI(self,tempData)
                        print("game_name: "+ game_name)
                        if 'TMM' in game_name:
                            tempData.update({'game_type':'Ranked TMM'})
                            honCMD.updateStatus(self,tempData)
                            honCMD.updateStatus_GI(self,tempData)
                        else:
                            tempData.update({'game_type':'Public Games'})
                            honCMD.updateStatus(self,tempData)
                            honCMD.updateStatus_GI(self,tempData)
                    if "INFO_MAP name:" in line:
                        game_map = re.findall(r'"([^"]*)"', line)
                        game_map = game_map[0]
                        tempData.update({'game_map':game_map})
                        honCMD.updateStatus(self,tempData)
                        honCMD.updateStatus_GI(self,tempData)
                        print("map: "+ game_map)
                    if "INFO_SETTINGS mode:" in line:
                        game_mode = re.findall(r'"([^"]*)"', line)
                        game_mode = game_mode[0]
                        game_mode = game_mode.replace('Mode_','')
                        tempData.update({'game_mode':game_mode})
                        honCMD.updateStatus(self,tempData)
                        honCMD.updateStatus_GI(self,tempData)
                        print("game_mode: "+ game_mode)
                        honCMD.updateStatus(self,tempData)
                        honCMD.updateStatus_GI(self,tempData)
                        match_status.update({'match_info_obtained':True})
                        print(f"Match Started: {match_status}")
    def get_lobby_information(self):
        tempData = {}
        if self.server_status['slave_log_location'] == "empty":
            honCMD().get_current_game_log()
        #softSlave = mData.getData(self,"loadSoftSlave")
        #hardSlave = mData.getData(self,"loadHardSlave")

        #if softSlave is not hardSlave: #and check_lobby is True:
        #
        #   Commenting below 3 lines due to an error with encoding. Trying to be consistent
        # dataL = open(self.server_status['slave_log_location'],encoding='utf-16-le')
        # data = dataL.readlines()
        # dataL.close()
        with open (self.server_status['slave_log_location'], "r", encoding='utf-16-le') as f:
            #
            #   Someone has connected to the server and is about to host a game
            for line in f:
                if "Name: " in line:
                    host = line.split(": ")
                    host = host[2].replace('\n','')
                    tempData.update({'game_host':host})
                    honCMD.updateStatus(self,tempData)
                    print ("host: "+host)
                if "Version: " in line:
                    version = line.split(": ")
                    version = version[2].replace('\n','')
                    tempData.update({'game_version':version})
                    honCMD.updateStatus(self,tempData)
                    print("version: "+version)
                if "] IP: " in line:
                    client_ip = line.split(": ")
                    client_ip = client_ip[2].replace('\n','')
                    tempData.update({'client_ip':client_ip})
                    honCMD.updateStatus(self,tempData)
                    print(client_ip)
                #
                #   Arguments passed to server, and lobby starting
                if "GAME_CMD_CREATE_GAME" in line:
                    print("lobby starting....")
                    test = line.split(' ')
                    for parameter in test:
                        if "map:" in parameter:
                            map = parameter.split(":")
                            map = map[1]
                            tempData.update({'game_map':map})
                            print("map: "+ map)
                        if "mode:" in parameter:
                            mode = parameter.split(":")
                            mode = mode[1]
                            tempData.update({'game_mode':mode})
                            print("mode: "+ mode)
                        if "teamsize:" in parameter:
                            teamsize = parameter.split(":")
                            teamsize = teamsize[1]
                            slots = int(teamsize)
                            slots *= 2
                            tempData.update({'slots':slots})
                            print("teamsize: "+ teamsize)
                            print("slots: "+ str(slots))
                        if "spectators:" in parameter:
                            spectators = parameter.split(":")
                            spectators = spectators[1]
                            spectators = int(spectators)
                            tempData.update({'spectators':spectators})
                            print("spectators: "+ str(spectators))
                        if "referees:" in parameter:
                            referees = parameter.split(":")
                            referees = referees[1]
                            referees = int(referees)
                            tempData.update({'referees':referees})
                            print("referees: "+ str(referees))
                    try:
                        total_slots = slots + spectators + referees
                    except Exception: total_slots = 10
                    #
                    #   Set firstrunthrough to false so we don't accidentally come back here and waste IO.
                    #   Also set some other booleans for code logic later on
                    self.first_run = False
                    self.just_collected = True
                    self.lobby_created = True

                    tempData.update({'first_run':self.first_run})
                    tempData.update({'just_collected':self.just_collected})
                    tempData.update({'lobby_created':self.lobby_created})
                    tempData.update({'total_slots':total_slots})
                    tempData.update({'update_embeds':True})
                    tempData.update({'tempcount':-5})

                    honCMD.updateStatus(self,tempData)
                    match_status.update({'lobby_info_obtained':True})
                    #self.server_status.update[{"first_run":"true"}]
                    #self.server_status.update[{'just_collected':self.just_collected}]
                    #self.server_status.update[{'lobby_created':self.lobby_created}]
                elif "Successfully got a match ID" in line:
                    self.first_run = False
                    self.just_collected = True
                    self.lobby_created = True

                    tempData.update({'first_run':self.first_run})
                    tempData.update({'just_collected':self.just_collected})
                    tempData.update({'lobby_created':self.lobby_created})
                    honCMD.updateStatus(self,tempData)
        f.close()
        return tempData
    def check_game_ended(self):
        #
        if self.server_status["match_log_location"] == "empty":
            return False

        hard_data = honCMD.compare_filesizes(self,self.server_status["game_log_location"],"match")
        soft_data = os.stat(self.server_status['game_log_location']).st_size # initial file size

        if soft_data > hard_data:
            with open (self.server_status['match_log_location'], "r", encoding='utf-16-le') as f:
                #if self.server_status['game_started'] == False:
                for line in f:
                    if line.startswith("GAME_END"):
                        return True
            f.close()
        return
    def check_game_started(self):
        tempData = {}
        #
        if self.server_status["game_log_location"] == "empty":
            honCMD().get_current_game_log()
        #print("checking for game started now")

        hard_data = honCMD.compare_filesizes(self,self.server_status["game_log_location"],"game")
        soft_data = os.stat(self.server_status['game_log_location']).st_size # initial file size

        tempData = {}
        if soft_data > hard_data:
            self.server_status.update({'slave_log_checked':True})
            with open (self.server_status['game_log_location'], "r", encoding='utf-16-le') as f:
                #if self.server_status['game_started'] == False:
                for line in f:
                    if "PLAYER_SELECT" in line or "PLAYER_RANDOM" in line or "GAME_START" in line or "] StartMatch" in line:
                        tempData.update({'game_started':True})
                        tempData.update({'tempcount':-5})
                        tempData.update({'update_embeds':True})
                        match_status.update({'now':'in game'})
                        honCMD.updateStatus(self,tempData)
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Match started. {match_status['match_id']}","INFO")
                        return True
            f.close()
        return
    def compare_num_matches_played(self):
        tempList = []
        total_games_file = f"{processed_data_dict['sdc_home_dir']}\\cogs\\total_games_played"
        if (exists(total_games_file)):
            #
            #   Read last value for total games played
            with open(total_games_file, 'r') as f:
                total_games_from_file = f.read().splitlines()
            f.close()
        #
        #   Add new values to file
        for item in os.listdir(processed_data_dict['hon_logs_dir']):
            if "game" in item or (item.startswith("M") and item.endswith(".log")):
                tempList.append(item)
        if not tempList:
            print("NO GAME FILE EITHER, we should make one")
            with open(processed_data_dict['hon_logs_dir']+'\\M0000.log', 'w'): pass
            tempList.append("M0000.log")


        try:
            resulting_list = sorted(list(set(total_games_from_file + tempList)))
        except UnboundLocalError:
            resulting_list = sorted(tempList)

        games_played_now = len(resulting_list)
        games_played_then = len(total_games_from_file)

        if games_played_now > games_played_then:
            with open(total_games_file, 'wt') as f:
                f.write('\n'.join(resulting_list))
            f.close()
            return games_played_now
        else:
            return False
    def get_current_match_log(self):
        try:
            # get list of files that matches pattern
            #pattern="M*.log"
            pattern=f"{match_status['match_id']}.log"
            #pattern="M*log"

            files = list(filter(os.path.isfile,glob.glob(pattern)))

            # sort by modified time
            files.sort(key=lambda x: os.path.getmtime(x))

            # get last item in list
            matchLoc = files[-1]

            self.server_status.update({"match_log_location":matchLoc})
            print("Most recent match log, matching {}: {}".format(match_status["match_id"],matchLoc))

            # for item in os.listdir():
            #     if "game" in item or (item.startswith("M") and item.endswith(".log")):
            #         tempList.append(item)
            # gameLoc = tempList[len(tempList)-1]
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            pass
        return True
    def launch_keeper():
        try:
            subprocess.run([f"{processed_data_dict['sdc_home_dir']}\\cogs\\keeper.exe","ban"],stdout=subprocess.DEVNULL)
        except Exception:
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Failed to execute keeper.exe","WARNING")
    def get_current_game_log(self):
        gameLoc = None
        try:
            # get list of files that matches pattern
            pattern=f"Slave{processed_data_dict['svr_id']}_{match_status['match_id']}_console.clog"

            files = list(filter(os.path.isfile,glob.glob(pattern)))

            # sort by modified time
            files.sort(key=lambda x: os.path.getmtime(x))

            # get last item in list
            gameLoc = files[-1]
            self.server_status.update({"game_log_location":gameLoc})
            print("Most recent game log, matching {}: {}".format(match_status["match_id"],gameLoc))
            return gameLoc
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            pass
    def reset_log_mtime_files(self):
        mtime_files = [f"{processed_data_dict['sdc_home_dir']}\\cogs\\slave_mtime",f"{processed_data_dict['sdc_home_dir']}\\cogs\\game_mtime",f"{processed_data_dict['sdc_home_dir']}\\cogs\\match_mtime"]
        for mtime_file in mtime_files:
            try:
                if exists(mtime_file): os.remove(mtime_file)
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
    def move_replays_and_stats2(self):
        print("Moving replays to replay manager directory and cleaning temporary files...")
        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}","Moving replays to replay manager directory and cleaning temporary files...","INFO")
        if 'match_id' not in match_status:
            return False

        match_id = match_status['match_id'].replace("M","")
        replays_dest_dir = f"{processed_data_dict['hon_manager_dir']}Documents\\Heroes of Newerth x64\\game\\replays\\"

        try:
            if not exists(processed_data_dict['hon_replays_dir']):
                os.makedirs(processed_data_dict['hon_replays_dir'])
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        try:
            files = os.listdir(processed_data_dict['hon_replays_dir'])
            for file in files:
                if match_id not in file:
                    if not os.path.isfile(processed_data_dict['hon_replays_dir']+"\\"+file):
                        shutil.rmtree(processed_data_dict['hon_replays_dir']+"\\"+file,onerror=honCMD.onerror)
                    else:
                        if file.endswith(".honreplay"):
                            print(f"moving replay {file} to {processed_data_dict['hon_replays_dir']}")
                            if not exists(replays_dest_dir+file):
                                shutil.move(processed_data_dict['hon_replays_dir']+"\\"+file,replays_dest_dir)
                            else:
                                if os.stat(file) > os.stat(replays_dest_dir+file):
                                    os.remove(replays_dest_dir+file)
                                else:
                                    os.remove(file)
                                    shutil.move(processed_data_dict['hon_replays_dir']+"\\"+file,replays_dest_dir)
                        else:
                            print("deleting temporary file "+file)
                            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"deleting temporary file {file}","WARNING")
                            os.remove(processed_data_dict['hon_replays_dir']+"\\"+file)
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
    def start_autoping_responder():
        try:
            # create a thread
            thread = Thread(target=udp_lsnr.Listener.start_listener)
            thread.start()
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Couldn't start the UDP listener required for auto server selection\n{traceback.format_exc()}","WARNING")
    def move_replays_and_stats(self,whocalledme):
        self.server_status.update({'replays_cleaned_once':True})
        print(whocalledme)
        print("Moving replays to replay manager directory and cleaning temporary files...")
        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}","Moving replays to replay manager directory and cleaning temporary files...","INFO")
        if 'match_id' not in match_status:
            return False
        match_id = match_status['match_id'].replace("M","")
        replays_dest_dir = f"{processed_data_dict['hon_manager_dir']}Documents\\Heroes of Newerth x64\\game\\replays\\"
        try:
            if not exists(processed_data_dict['hon_replays_dir']):
                os.makedirs(processed_data_dict['hon_replays_dir'])
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        try:
            files = os.listdir(processed_data_dict['hon_replays_dir'])
            for file in files:
                #if os.path.isfile(processed_data_dict['hon_replays_dir']+"\\"+file):
                #find = re.compile(r"^([^.]*).*")
                if match_id not in file or (match_id in file and not exists(f"{processed_data_dict['hon_replays_dir']}\\{match_id}.tmp")):
                    try:
                        if not os.path.isfile(processed_data_dict['hon_replays_dir']+"\\"+file):
                            shutil.rmtree(processed_data_dict['hon_replays_dir']+"\\"+file,onerror=honCMD.onerror)
                        else:
                            if file.endswith(".honreplay"):
                                print(f"moving replay {file} to {processed_data_dict['hon_replays_dir']}")
                                if not exists(replays_dest_dir+file):
                                    shutil.move(processed_data_dict['hon_replays_dir']+"\\"+file,replays_dest_dir)
                                else:
                                    if os.stat(file) > os.stat(replays_dest_dir+file):
                                        os.remove(replays_dest_dir+file)
                                    else:
                                        os.remove(file)
                                        shutil.move(processed_data_dict['hon_replays_dir']+"\\"+file,replays_dest_dir)
                            else:
                                print("deleting temporary file "+file)
                                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"deleting temporary file {file}","WARNING")
                                os.remove(processed_data_dict['hon_replays_dir']+"\\"+file)
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                # else:
                #     if match_id not in file_name:
                #         if not os.path.isfile(processed_data_dict['hon_replays_dir']+"\\"+file):
                #             shutil.rmtree(processed_data_dict['hon_replays_dir']+"\\"+file,onerror=honCMD.onerror)
                #         else:
                #             print("deleting temporary file "+file)
                #             if not os.path.isfile(processed_data_dict['hon_replays_dir']+"\\"+file):
                #                 shutil.rmtree(processed_data_dict['hon_replays_dir']+"\\"+file,onerror=honCMD.onerror)
                #             else:
                #                 os.remove(processed_data_dict['hon_replays_dir']+"\\"+file)
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        #
        # move stats files off into the manager directory. so manager can resubmit stats
        stats_dest_dir = f"{processed_data_dict['hon_manager_dir']}Documents\\Heroes of Newerth x64\\game\\logs\\"
        try:
            files = os.listdir(processed_data_dict['hon_logs_dir'])
            for file in files:
                if os.path.isfile(processed_data_dict['hon_logs_dir']+"\\"+file):
                    if file.endswith(".stats"):
                        try:
                            shutil.move(processed_data_dict['hon_logs_dir']+"\\"+file,stats_dest_dir)
                        except Exception:
                            print(traceback.format_exc())
                            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        except Exception:
            print(traceback.format_exc())
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
    """
    """
    def playerCount(self,server,config):
        check = subprocess.Popen([config[0]['hon_data']['count_players_exe'],server['config']['file_name']],stdout=subprocess.PIPE, text=True)
        i = int(check.stdout.read())
        check.terminate()
        return i
    def playerCount_pid(self):
        check = subprocess.Popen([processed_data_dict['player_count_exe_loc'],str(self.server_status['hon_pid'])],stdout=subprocess.PIPE, text=True)
        i = int(check.stdout.read())
        check.terminate()
        return i
    def playerCount_pid_raw(self,pid,config):
        pid = str(pid)
        check = subprocess.Popen([config[0]['hon_data']['count_players_exe'],pid],stdout=subprocess.PIPE, text=True)
        i = int(check.stdout.read())
        check.terminate()
        return i
    def playerCountAPI(self,seed_data):
        check = subprocess.Popen([seed_data['player_count_exe'],seed_data['name']],stdout=subprocess.PIPE, text=True)
        i = int(check.stdout.read())
        check.terminate()
        return i
    def get_process_affinity(proc):
        proc_affinity = proc.cpu_affinity()
        proc_affinity = ','.join(str(x) for x in proc_affinity)
        return proc_affinity
    def get_process_priority(proc_name):
        pid = False
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                pid = proc.pid
        if pid:
            p = next((proc for proc in psutil.process_iter() if proc.pid == pid),None)
            prio = p.nice()
            prio = (str(prio)).replace("Priority.","")
            prio = prio.replace("_PRIORITY_CLASS","")
            if prio == "64": prio = "IDLE"
            elif prio == "128": prio = "HIGH"
            elif prio == "256": prio = "REALTIME"
            return prio
        else: return "N/A"
    def count_skipped_frames(self):
        simple_match_data = {}
        skipped_frames = 0
        count_frames=False
        count_frames_from=0
        frame_size = 0
        frame_sizes = []
        if self.server_status['game_log_location'] == 'empty':
            honCMD().get_current_game_log()
        with open(self.server_status['game_log_location'], "r", encoding='utf-16-le') as f:
            if match_status['skipped_frames_after_line'] == 0:
                for num,line in list(enumerate(f, 1)):
                    if any(x in line for x in ["PLAYER_SELECT","PLAYER_RANDOM","GAME_START","] StartMatch"]):
                        count_frames = True
                        count_frames_from = num
                        match_status.update({'skipped_frames_after_line':count_frames_from})
        if count_frames:
            with open(self.server_status['game_log_location'], "r", encoding='utf-16-le') as f:
                for num, line in list(enumerate(f, match_status['skipped_frames_after_line'])):
                    if "Skipped" in line or "skipped" in line:
                        pattern = "\(([^\)]+)\)"
                        skipped_frames+=1
                        try:
                            frame_size = re.findall(r'\(([^\)]+)\)', line)
                            frame_size = frame_size[0]
                            frame_size = frame_size.split(" ")
                            frame_sizes.append(int(frame_size[0]))
                        except Exception: pass
                match_status.update({'skipped_frames_after_line':num})
        try:
            total_time_lagging_msecs = sum(frame_sizes)
            # convert to seconds
            total_time_lagging_secs = total_time_lagging_msecs / 1000
        except Exception:
            total_time_lagging = None
        return total_time_lagging_secs

    def simple_match_data(log,type):
        simple_match_data = {}
        simple_match_data.update({'match_time':'In-Lobby phase...'})
        skipped_frames = 0
        in_game=False
        match_status.update({'skipped_frames_from_line':0})
        frame_size = 0
        frame_sizes = []
        try:
            match_id = re.search(r'M([0-9]+)', log)
            match_id = match_id.group(0)
            simple_match_data.update({'match_id':match_id})
        except Exception:
            simple_match_data.update({'match_id':'N/A'})
        if type == "match":
            with open (log, "r", encoding='utf-16-le') as f:
                #for num,line in reversed(list(f)):
                for num, line in list(enumerate(f, 1)):
                    if "PLAYER_SELECT" in line or "PLAYER_RANDOM" in line or "GAME_START" in line or "] StartMatch" in line:
                        if simple_match_data['match_time'] in ('In-Lobby phase...'):
                            simple_match_data.update({'match_time':'Hero select phase...'})
                    if "Phase(5)" in line:
                        in_game = True
                        if match_status['skipped_frames_from_line'] == 0:
                            match_status.update({'skipped_frames_from_line':num})
                        break
            if in_game:
                with open (log, "r", encoding='utf-16-le') as f:
                    for num, line in reversed(list(enumerate(f, 1))):
                        if "Server Status" in line and simple_match_data['match_time'] in ('In-Lobby phase...','Hero select phase...'):
                            #Match Time(00:07:00)
                            if "Match Time" in line:
                                pattern="(Match Time\()(.*)(\))"
                                try:
                                    match_time=re.search(pattern,line)
                                    match_time = match_time.group(2)
                                    simple_match_data.update({'match_time':match_time})
                                    #tempData.update({'match_log_last_line':num})
                                    #print("match_time: "+ match_time)
                                    continue
                                except AttributeError as e:
                                    pass
                        if num > match_status['skipped_frames_from_line']:
                            if "Skipped" in line or "skipped" in line:
                                pattern = "\(([^\)]+)\)"
                                skipped_frames+=1
                                try:
                                    frame_size = re.findall(r'\(([^\)]+)\)', line)
                                    frame_size = frame_size[0]
                                    frame_size = frame_size.split(" ")
                                    frame_sizes.append(int(frame_size[0]))
                                except Exception: pass
        try:
            largest_frame = max(frame_sizes)
            simple_match_data.update({'largest_skipped_frame':f"{largest_frame}msec"})
        except Exception:
            simple_match_data.update({'largest_skipped_frame':"No skipped frames."})
        simple_match_data.update({'skipped_frames':skipped_frames})
        return simple_match_data

    def wait_for_replay(self,wait):
        global replay_wait
        replay_wait +=1
        match_id = match_status['match_id'].replace("M","")
        if not exists(f"{processed_data_dict['hon_replays_dir']}\\{match_id}.tmp") and exists(f"{processed_data_dict['hon_replays_dir']}\\M{match_id}.honreplay"):
            if os.stat(f"{processed_data_dict['hon_replays_dir']}\\M{match_id}.honreplay").st_size > 0:
                replay_wait = 0
                print("Replay generated. Preparing server for next match..")
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"[{match_status['match_id']}] {processed_data_dict['hon_replays_dir']}\\{match_status['match_id']}.honreplay generated. Closing server now.","INFO")
                #match_status.update({'now':'idle'})
                honCMD().initialise_variables("reload","reload - called by post game replay checker")
                return True
        else:
            print(f"[{match_status['match_id']}] Generating replay for match. Delaying restart for up to 5 minutes ({replay_wait}/{wait}sec until server is restarted).")
            if 'replay_notif_in_log' not in match_status or match_status['replay_notif_in_log'] == False:
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"[{match_status['match_id']}] Match finished. Waiting for generation of replay (can take up to {wait} seconds","INFO")
                match_status.update({'replay_notif_in_log':True})
            if replay_wait >= wait:
                replay_wait = 0
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"[{match_status['match_id']}] timed out ({replay_wait}/{wait} seconds) waiting for replay. Moving to next game..","INFO")
                #honCMD().restartSERVER(False,"Restarting server because it has taken too long to generate the replay.")
                return False
            return False
    def check_cookie(server_status,log,name):
        def write_mtime(log,name):
            last_modified_time_file = f"{server_status['sdc_home_dir']}\\cogs\\{name}_mtime"
            #
            #   This reads the data if it exists
            if (exists(last_modified_time_file)):
                with open(last_modified_time_file, 'r') as last_modified:
                    lastmodData = last_modified.readline()
                last_modified.close()
                try:
                    lastmodData = int(lastmodData)
                except Exception: pass
                #
                #   Gets the current byte size of the log
                fileSize = os.stat(log).st_size
                #
                #   After reading data set temporary file to current byte size
                with open(last_modified_time_file, 'w') as last_modifiedw:
                    last_modifiedw.write(f"{fileSize}")
                last_modifiedw.close()
                return lastmodData
            #
            #   If there was no temporary file to load data from, create it.
            else:
                try:
                    fileSize = os.stat(log).st_size
                    with open(last_modified_time_file, 'w') as last_modified:
                        last_modified.write(f"{fileSize}")
                    last_modified.close()
                except Exception:
                    print(traceback.format_exc())
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                    pass
                return fileSize
        hard_data = write_mtime(log,name)
        soft_data = os.stat(log).st_size # initial file size
        status={}
        # if (soft_data > hard_data) or 'first_check' not in status:
        session_cookie_errors = ["session cookie request failed!","invalid session cookie","no session cookie returned"]
        with open (log, "r", encoding='utf-16-le') as f:
            for line in reversed(list(f)):
                for item in session_cookie_errors:
                    if item in line.lower():
                        return "no cookie"
                    elif "new session cookie [" in line.lower():
                        return "connected"
            return "pending"
        return True
        # status.update({'first_check':'Done'})
        #return True
        # else:
        #     return True
    def clean_old_logs(self):
        print("Performing cleanup of old log files (older than 7 days)...")
        paths = [f"{processed_data_dict['hon_logs_dir']}",f"{processed_data_dict['hon_logs_dir']}\\diagnostics"]
        now = time.time()
        count=0
        for path in paths:
            for f in os.listdir(path):
                f = os.path.join(path, f)
                if os.stat(f).st_mtime < now - 7 * 86400:
                    if os.path.isfile(f):
                        try:
                            os.remove(os.path.join(path, f))
                            count+=1
                            print("removed "+f)
                        except PermissionError:
                            pass
                        except Exception:
                            print(traceback.format_exc())
                            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        print(f"DONE. Cleaned {count} files.")
        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Cleaned {count} files","INFO")
    def changePriority(self,priority_realtime):
        if priority_realtime:
            if processed_data_dict['process_priority'] == "normal":
                self.server_status['hon_pid_hook'].nice(psutil.NORMAL_PRIORITY_CLASS)
            elif processed_data_dict['process_priority'] == "high":
                self.server_status['hon_pid_hook'].nice(psutil.HIGH_PRIORITY_CLASS)
            elif processed_data_dict['process_priority'] == "realtime":
                self.server_status['hon_pid_hook'].nice(psutil.REALTIME_PRIORITY_CLASS)
            print(f"priority set to {processed_data_dict['process_priority']}")
            self.server_status.update({'priority_realtime':priority_realtime})
        else:
            self.server_status['hon_pid_hook'].nice(psutil.IDLE_PRIORITY_CLASS)
            print("priority set to idle")
            self.server_status.update({'priority_realtime':priority_realtime})
        return priority_realtime

    def updateStatus(self,data):
        #
        #   Combine temp data into the sever_status dictionary
        server_status_dict.update(data)
        #print("updated dictionary: " + str(server_status_dict))
        return
    def updateStatus_GI(self,data):
        #
        #   Combine temp data into the sever_status dictionary
        match_status.update(data)
        #print("updated dictionary: " + str(server_status_dict))
        return

    def check_upstream_patch(self): # function to check latest version on masterserver
        import requests
        import re

        version=None
        url = 'http://api.kongor.online/patcher/patcher.php'
        payload = {
            'latest' : '',
            'os': 'was-crIac6LASwoafrl8FrOa',
            'arch' : 'x86_64'
            }
        try:
            x = requests.post(url,data=payload)
            data=x.text
            data=re.split(';s:\d+:',data)
        except Exception:
            print("Error reading data from masterserver.")
            return False

        for i in range(len(data)):
            if '"latest_version"' in data[i]:
                version=data[i+1]

        if version != None:
            if '"' in version:
                version=version.replace('"','')
            return version
        else:
            return False

    def getStatus(self):
        return server_status_dict
    def getDataDict(self):
        return processed_data_dict
    def getMatchInfo(self):
        return match_status
   #   Starts server
    def initialise_variables(self,reset_type,whocalledme):
        if reset_type == "soft":
            print(f"Initialising variables (soft). Data Dump: {dmgr.mData().return_simple_dict(processed_data_dict)}")
            honCMD.append_line_to_file(self,f"{processed_data_dict['app_log']}",f"Initialising variables (soft). Data Dump: {dmgr.mData().return_simple_dict(processed_data_dict)}","INFO")
            match_status.update({'now':'idle'})
            match_status.update({'match_info_obtained':False})
            self.server_status.update({"game_log_location":"empty"})
            self.server_status.update({"match_log_location":"empty"})
            self.server_status.update({"slave_log_location":"empty"})
            return
        #print(f"Initialising variables. Data dump: {processed_data_dict}")

        honCMD.append_line_to_file(self,f"{processed_data_dict['app_log']}",f"Initialising variables. Data dump: {processed_data_dict}","INFO")
        #
        # Remove log files older than 7 days
        if reset_type == "reload":
            try:
                if match_status['first_run'] == False:
                    print("lobby closed.")
                honCMD().clean_old_logs()
                honCMD().move_replays_and_stats(whocalledme)
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        self.first_run = True
        self.just_collected = False
        self.game_started = False
        self.tempcount = -5
        self.embed_updated = False
        self.lobby_created = False
        self.last_restart = honCMD.getData(self,"lastRestart")
        honCMD().getData("update_last_restarted")
        #
        #   Initialise some variables upon hon server starting
        self.server_status.update({"last_restart":self.last_restart})
        self.server_status.update({"first_run":self.first_run})
        self.server_status.update({"just_collected":self.just_collected})
        self.server_status.update({"game_started":self.game_started})
        self.server_status.update({"tempcount":self.tempcount})
        self.server_status.update({'update_embeds':False})
        self.server_status.update({"embed_updated":self.embed_updated})
        self.server_status.update({"lobby_created":self.lobby_created})
        self.server_status.update({"game_map":"empty"})
        self.server_status.update({"game_type":"empty"})
        self.server_status.update({"game_mode":"empty"})
        self.server_status.update({"game_host":"empty"})
        self.server_status.update({"game_name":"empty"})
        self.server_status.update({"game_version":"empty"})
        self.server_status.update({"spectators":0})
        self.server_status.update({"slots":10})
        self.server_status.update({"referees":0})
        self.server_status.update({"client_ip":"empty"})
        self.server_status.update({"match_info_obtained":False})
        self.server_status.update({'replay_notif_in_log':False})
        self.server_status.update({"priority_realtime":False})
        self.server_status.update({"restart_required":False})
        self.server_status.update({"game_log_location":"empty"})
        self.server_status.update({"match_log_location":"empty"})
        self.server_status.update({"slave_log_location":"empty"})
        self.server_status.update({"total_games_played_prev":honCMD.getData(self,"TotalGamesPlayed")})
        self.server_status.update({"total_games_played":honCMD.getData(self,"TotalGamesPlayed")})
        self.server_status.update({'elapsed_duration':0})
        if reset_type == "restart":
            self.server_status.update({'pending_restart':False})
            self.server_status.update({'server_ready':False})
            self.server_status.update({'server_starting':True})
            # try:
            #     honCMD().clean_old_logs()
            #     honCMD().move_replays_and_stats()
            # except Exception:
            #     print(traceback.format_exc())
            #     honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        self.server_status.update({'cookie':True})
        if processed_data_dict['use_proxy']=='True':
            self.server_status.update({'proxy_online':False})
        self.server_status.update({'scheduled_shutdown':False})
        self.server_status.update({'update_embeds':True})
        self.server_status.update({"hard_reset":False})
        self.server_status.update({'crash':True})
        self.server_status.update({'server_start_attempts':0})
        self.server_status.update({'at_least_2_players':False})
        honCMD().reset_log_mtime_files()

        #
        # Match info dictionary
        match_status.update({'match_log_last_line':0})
        match_status.update({'match_time':'Preparation phase..'})
        match_status.update({'match_info_obtained':False})
        match_status.update({'lobby_info_obtained':False})
        match_status.update({'now':'idle'})
        match_status.update({'first_run':True})
        match_status.update({'skipped_frames_after_line':0})

    def assign_cpu(self):
        self.server_status['hon_pid_hook'].cpu_affinity([processed_data_dict['svr_affinity'][0],processed_data_dict['svr_affinity'][1]])
        print(f"Server assigned to CPU cores: {processed_data_dict['svr_affinity']}")

    def start_server(self,config,reason):
        """
            Check for running server instances, or start one if none is running
        """

        log_msg = f"Starting HoN server. Reason: {reason}"
        print(log_msg)
        self.append_line_to_file(config[0]['application_data']['log_file'],log_msg,"INFO")

        #   check for existing process for this instance
        hon_process_name = self.server['data']['config']['file_name']
        if honCMD.check_proc(hon_process_name):
            hon_procs = []
            for proc in psutil.process_iter():
                if proc.name() == hon_process_name:
                    hon_procs.append(proc)

            timer = 0
            while len(hon_procs) > 0:
                for i in range(len(hon_procs)):
                    if self.playerCount_pid_raw(hon_procs[i].pid,config) >= 0:
                        hon_pid = hon_procs.pop(i)
                time.sleep(1)
                timer+=1
                if timer >= 180:
                    timer = 0
                    server.update({'status':'failed'})
                    return False
                    # TODO: LOG HERE
            #   update the process information with the healthy instance PID. Healthy playercount is either -3 (off) or >= 0 (alive)
            server.update({
                'status':f'{"idle" if self.playerCount_pid_raw(hon_pid,config) == 0 else "online"}',
                '_pid':proc.pid,
                '_proc':proc,
                '_proc_hook':psutil.Process(pid=proc.pid),
                '_pid_owner':proc.username()
            })

            try:
                honCMD().initialise_variables("","server start - but found pid")
                return server
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{config[0]['application_data']['log_file']}",f"{traceback.format_exc()}","WARNING")
            return False
        else:
            """ The process hasn't been found. Begin code to prepare starting server """

            #   prepare UDP listener port for the UDP auto-server selection listener, for best ping response
            if processed_data_dict['use_proxy'] == 'False':
                udp_listener_port = int(processed_data_dict['game_starting_port']) - 1
            else:
                udp_listener_port = int(processed_data_dict['game_starting_port']) + 10000 - 1

            if not honCMD.check_port(udp_listener_port):
                honCMD.start_autoping_responder()

            free_mem = psutil.virtual_memory().free
            #   HoN server instances use up to 1GM RAM per instance. Check if this is free before starting.
            if free_mem > 1000000000:
                #   set the environment
                #   Server instances write files to location dependent on USERPROFILE and APPDATA variables
                os.environ["USERPROFILE"] = processed_data_dict['hon_home_dir']
                os.environ["APPDATA"] = processed_data_dict['hon_root_dir']
                #   Clean up temporary old files
                #   These exist because the files have been replaced with newer versions. To avoid collision, the previous files were renamed
                old_hon_exe1 = f"{processed_data_dict['hon_directory']}HON_SERVER_{processed_data_dict['svr_id']}_old.exe"
                old_hon_exe2 = f"{processed_data_dict['hon_directory']}KONGOR_ARENA_{processed_data_dict['svr_id']}_old.exe"
                if exists(old_hon_exe1):
                    try:
                        os.remove(old_hon_exe1)
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                if exists(old_hon_exe2):
                    try:
                        os.remove(old_hon_exe2)
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")

                # gather networking details
                print("collecting port info...")
                tempData = {}
                svr_port = int(processed_data_dict['game_starting_port']) + processed_data_dict['incr_port']
                svr_proxyport = svr_port + 10000
                svr_proxyLocalVoicePort = int(processed_data_dict['voice_starting_port']) + processed_data_dict['incr_port']
                svr_proxyRemoteVoicePort = svr_proxyLocalVoicePort + 10000
                if 'static_ip' not in processed_data_dict:
                    try:
                        svr_ip = dmgr.mData.getData(self,"svr_ip")
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                        svr_ip = processed_data_dict['svr_ip']
                else:
                    svr_ip = processed_data_dict['svr_ip']
                tempData.update({'svr_port':svr_port})
                tempData.update({'svr_proxyLocalVoicePort':svr_proxyLocalVoicePort})
                tempData.update({'svr_proxyport':svr_proxyport})
                tempData.update({'svr_proxyRemoteVoicePort':svr_proxyRemoteVoicePort})

                # update the global dictionary
                honCMD.updateStatus(self,tempData)

                #   Start the HoN Server!
                if processed_data_dict['use_proxy']=='True':
                    if not honCMD.check_port(svr_proxyport):
                        print (f"proxy port {svr_proxyport} not online")
                        return "proxy"

                # remove any pending shutdown or pending restart files on startup
                honCMD.check_for_updates(self,"pending_restart")
                honCMD.check_for_updates(self,"pending_shutdown")


                # prepare the server commandline, and start the server!
                hon_commandline = dmgr.mData().return_commandline(processed_data_dict)
                DETACHED_PROCESS = 0x00000008
                if sys.platform == "win32":
                    self.honEXE = subprocess.Popen(hon_commandline,close_fds=True, creationflags=DETACHED_PROCESS)
                else:
                    self.honEXE = subprocess.Popen(hon_commandline,close_fds=True, start_new_session=True)

                honCMD().append_line_to_file(processed_data_dict['app_log'],f"Server starting. Reason: {reason}","INFO")

                # update the dictionary with the process PID information
                print(f"Server started (PID={self.honEXE.pid})")
                honPID = psutil.Process(pid=self.honEXE.pid)
                self.server_status.update({'hon_exe':self.honEXE})
                self.server_status.update({'hon_pid':self.honEXE.pid})
                self.server_status.update({'hon_pid_hook':honPID})
                self.server_status.update({'hon_pid_owner':honPID.username()})

                if processed_data_dict['core_assignment'] not in ("one core/server","two cores/server","two servers/core","three servers/core","four servers/core"):
                    log_msg = f"Program closing. Current value for core assignment: {processed_data_dict['core_assignment']}.\Accepted values: 'one core/server','two cores/server','two servers/core','three servers/core','four servers/core'"
                    print(log_msg)
                    honCMD().append_line_to_file(processed_data_dict['app_log'],log_msg,"WARNING")
                    honCMD().stopSELF(log_msg)

                honPID.cpu_affinity([processed_data_dict['svr_affinity'][0],processed_data_dict['svr_affinity'][1]])

                self.server_status['hon_pid_hook'].nice(psutil.IDLE_PRIORITY_CLASS)

                # Reload the dictionary. This is important as we want to start with a blank slate with every server restart.
                honCMD().initialise_variables("restart","called by server restart (no PID)")
                return True
            else:
                # insufficient RAM

                # Crash variable used to determine whether it's a standard server shut off or something went wrong
                self.server_status.update({'crash':True})
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Insufficient RAM to start server.","WARNING")
                return "ram"

    def stopSERVER(self,force,reason):
        """ StopServer: used to terminate the HoN server instance
        force is a boolean used to enforce the stoppage despite playercount """
        pcount = self.playerCount_pid()
        if self.playerCount_pid() <= 0 or force:
            for proc in psutil.process_iter():
                if proc.name() == processed_data_dict['hon_file_name']:
                    proc.terminate()
                    self.server_status.update({'hon_pid':'pending'})
                    log_msg = f"Server stopped (PID={proc.pid}). Reason: {reason}"
                    print(log_msg)
                    honCMD().append_line_to_file(processed_data_dict['app_log'],log_msg,"INFO")
            self.server_status.update({'update_embeds':True})
            self.server_status.update({'crash':False})
            return True
        return

    def restartSERVER(self,force,reason):
        if self.playerCount_pid() == 0 or force:
            hard_reset = honCMD().check_for_updates("pending_restart")
            if hard_reset:
                self.server_status.update({'hard_reset':True})
                honCMD().restartSELF("Server was about to restart normally, then found a scheduled restart file.")
            else:
                log_msg = f"Server about to restart. Reason: {reason}"
                print(log_msg)
                honCMD().append_line_to_file(processed_data_dict['app_log'],log_msg,"INFO")
                try:
                    honCMD().stopSERVER(force,reason)
                except Exception:
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                #
                #   Code is stuck waiting for server to turn off
                self.server_status.update({'server_restarting':True})
                #self.server_status.update({'update_embeds':True})
                while self.playerCount_pid() >= 0:
                    time.sleep(1)
                #
                #   Once detects server is offline with above code start the server
                try:
                    honCMD().startSERVER(reason)
                except Exception:
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        else:
            self.server_status.update({'update_embeds':True})
            self.server_status.update({'tempcount':-5})

        return True

    def restartSELF(self,reason):
        log_msg = f"Server restarting HARD - means we are restarting the actual service or adminbot console in addition to the hon server. Reason: {reason}"
        print(log_msg)
        honCMD().append_line_to_file(processed_data_dict['app_log'],log_msg,"INFO")
        os.chdir(processed_data_dict['sdc_home_dir'])
        subprocess.Popen([f"start",f"adminbot{processed_data_dict['svr_id']}-launch.exe","restart"],shell=True)

    def stopSELF(self,reason):
        log_msg = f"Server stopping HARD - means we are intentionally stopping the service or adminbot console. Reason: {reason}"
        honCMD().append_line_to_file(processed_data_dict['app_log'],log_msg,"INFO")
        try:
            honCMD().stopSERVER(True,"Stopping as part of hard shutdown.")
        except Exception:
            honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            return
        if processed_data_dict['use_console'] == 'True':
            os._exit(0)
        else:
            os.system(f"net stop {processed_data_dict['app_name']}")
        #sys.exit(0)
    def reportPlayer(self,reason):
        #
        #   sinister behaviour detected, save log to file.
        #   Players can attempt to start a game on an uknown map file. This causes the server to crash and hang.
        #   We will firstly handle the error, restart the server, and then log the event for investigation.
        if self.server_status['slave_log_location'] == "empty":
            honCMD().getData("getLogList_Slave")
        t = time.localtime()
        timestamp = time.strftime('%b-%d-%Y_%H%M', t)
        with open(f"{processed_data_dict['sdc_home_dir']}\\suspicious\\evt-{timestamp}-{reason}.txt", 'w') as f:
            f.write(f"{reason}\n{processed_data_dict['svr_identifier']}\n{self.server_status['game_map']}\n{self.server_status['game_host']}\n{self.server_status['client_ip']}")
        honCMD().append_line_to_file(processed_data_dict['app_log'],f"Player reported ({self.server_status['game_host']}). Reason: {reason}. Deatils in {processed_data_dict['sdc_home_dir']}\\suspicious\\evt-{timestamp}-{reason}.txt","INFO")
        #save_path = f"{processed_data_dict['sdc_home_dir']}\\suspicious\\[{reason}]-{processed_data_dict['svr_identifier']}-{self.server_status['game_map']}-{self.server_status['game_host']}-{self.server_status['client_ip']}-{timestamp}.log"
        #shutil.copyfile(self.server_status['slave_log_location'], save_path)
    def time():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def append_line_to_file(self,file,text,level):
        timenow = honCMD.time()
        if not exists(file):
            with open (file, 'w') as f:
                f.close()
        with open(file, 'a+') as f:
            f.seek(0)
            data = f.read(100)
            if len(data) > 0:
                f.write("\n")
            f.write(f"[{timenow}] [{level}] {text}")
        if exists(file):
            filesize = os.path.getsize(file) >> 20
            if filesize > 10:
                open(file, 'w').close()
    def compare_filesizes(self,file,name):
        last_modified_time_file = f"{processed_data_dict['sdc_home_dir']}\\cogs\\{name}_mtime"
        lastmodData = 0
        #
        #   This reads the data if it exists
        if (exists(last_modified_time_file)):
            with open(last_modified_time_file, 'r') as last_modified:
                lastmodData = last_modified.readline()
            last_modified.close()
            try:
                lastmodData = int(lastmodData)
            except ValueError:
                os.remove(last_modified_time_file)
            #
            #   Gets the current byte size of the log
            fileSize = os.stat(file).st_size
            #
            #   After reading data set temporary file to current byte size
            with open(last_modified_time_file, 'w') as last_modifiedw:
                last_modifiedw.write(f"{fileSize}")
            last_modifiedw.close()
            return lastmodData
        #
        #   If there was no temporary file to load data from, create it.
        else:
            try:
                fileSize = os.stat(file).st_size
                with open(last_modified_time_file, 'w') as last_modified:
                    last_modified.write(f"{fileSize}")
                last_modified.close()
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                pass
            return fileSize
    def check_for_updates(self,type):
        temFile = processed_data_dict['sdc_home_dir']+"\\"+type
        if exists(temFile):
            if type == "pending_restart":
                remove_me=processed_data_dict['sdc_home_dir']+"\\"+"pending_shutdown"
                if exists(remove_me):
                    try:
                        os.remove(remove_me)
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            elif type == "pending_shutdown":
                remove_me=processed_data_dict['sdc_home_dir']+"\\"+"pending_restart"
                if exists(remove_me):
                    try:
                        os.remove(remove_me)
                    except Exception:
                        print(traceback.format_exc())
                        honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            try:
                os.remove(temFile)
                honCMD().append_line_to_file(processed_data_dict['app_log'],f"scheduled {type} detected.","INFO")
                #ctypes.windll.kernel32.SetConsoleTitleW(f"{processed_data_dict['app_name']} - {type}")
                return True
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
        else:
            #ctypes.windll.kernel32.SetConsoleTitleW(f"{processed_data_dict['app_name']}")
            return False
#
#   reads and parses hon server log data
    def getData(self, dtype):
        #
        #   We look if a file called "restart_required" exists. If it does we determine whether an update is pending for the bot, therefore needing to restart
        if dtype == "CheckSchdShutdown":
            temFile = processed_data_dict['sdc_home_dir']+"\\pending_shutdown"
            if exists(temFile):
                try:
                    os.remove(temFile)
                    return True
                except Exception:
                    print(traceback.format_exc())
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            else:
                return False
        if dtype == "TotalGamesPlayed":
            tempList = []
            total_games_file = f"{processed_data_dict['sdc_home_dir']}\\cogs\\total_games_played"
            if (exists(total_games_file)):
                #
                #   Read last value for total games played
                with open(total_games_file, 'r') as f:
                    total_games_from_file = f.read().splitlines()
                f.close()
            #
            #   Add new values to file
            for item in os.listdir(processed_data_dict['hon_logs_dir']):
                if "game" in item or (item.startswith("M") and item.endswith(".log")):
                    tempList.append(item)
            if not tempList:
                print("NO GAME FILE EITHER, we should make one")
                with open(processed_data_dict['hon_logs_dir']+'\\M0000.log', 'w'): pass
                tempList.append("M0000.log")
            try:
                resulting_list = sorted(list(set(total_games_from_file + tempList)))
            except UnboundLocalError:
                resulting_list = sorted(tempList)
            with open(total_games_file, 'wt') as f:
                f.write('\n'.join(resulting_list))
            f.close()
            total_games_played = len(resulting_list)
            return total_games_played
        if dtype == "CompareTotalGames":
            tempList = []
            total_games_file = f"{processed_data_dict['sdc_home_dir']}\\cogs\\total_games_played"
            if (exists(total_games_file)):
                #
                #   Read last value for total games played
                with open(total_games_file, 'r') as f:
                    total_games_from_file = f.read().splitlines()
                f.close()
            #
            #   Add new values to file
            for item in os.listdir(processed_data_dict['hon_logs_dir']):
                if "game" in item or (item.startswith("M") and item.endswith(".log")):
                    tempList.append(item)
            if not tempList:
                print("NO GAME FILE EITHER, we should make one")
                with open(processed_data_dict['hon_logs_dir']+'\\M0000.log', 'w'): pass
                tempList.append("M0000.log")


            try:
                resulting_list = sorted(list(set(total_games_from_file + tempList)))
            except UnboundLocalError:
                resulting_list = sorted(tempList)

            games_played_now = len(resulting_list)
            games_played_then = len(total_games_from_file)

            if games_played_now > games_played_then:
                with open(total_games_file, 'wt') as f:
                    f.write('\n'.join(resulting_list))
                f.close()
                return games_played_now
            else:
                return False

        elif dtype == "CheckInGame":
            tempData = {}
            total_games_played_prev_int = int(self.server_status['total_games_played_prev'])
            total_games_played_now_int = int(honCMD.getData(self,"TotalGamesPlayed"))
            #print ("about to check game started")
            #if (total_games_played_now_int > total_games_played_prev_int and os.stat(self.server_status['game_log_location']).st_size > 0):
            if (total_games_played_now_int > total_games_played_prev_int):
                #
                if self.server_status["game_log_location"] == "empty":
                    honCMD.getData(self,"getLogList_Game")
                #print("checking for game started now")

                hard_data = honCMD.compare_filesizes(self,self.server_status["game_log_location"],"game")
                soft_data = os.stat(self.server_status['game_log_location']).st_size # initial file size

                tempData = {}
                if soft_data > hard_data or 'slave_log_checked' not in self.server_status:
                    self.server_status.update({'slave_log_checked':True})
                    #TODO: check match_id actually works?
                    match_id = self.server_status['match_log_location']
                    match_id = match_id.replace(".log","")
                    with open (self.server_status['game_log_location'], "r", encoding='utf-16-le') as f:
                        if self.server_status['game_started'] == False:
                            for line in f:
                                if "PLAYER_SELECT" in line or "PLAYER_RANDOM" in line or "GAME_START" in line or "] StartMatch" in line:
                                    tempData.update({'game_started':True})
                                    tempData.update({'tempcount':-5})
                                    tempData.update({'update_embeds':True})
                                    honCMD.updateStatus(self,tempData)
                                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Match started. {match_id}","INFO")
                                    return True
                        else:
                            # for num, line in enumerate(f, 1):
                            #     if num > match_status['match_log_last_line']:
                            for line in reversed(list(f)):
                                if "Server Status" in line:
                                    #Match Time(00:07:00)
                                    if "Match Time" in line:
                                        pattern="(Match Time\()(.*)(\))"
                                        try:
                                            match_time=re.search(pattern,line)
                                            match_time = match_time.group(2)
                                            if match_time != match_status['match_time']:
                                                tempData.update({'match_time':match_time})
                                                #tempData.update({'match_log_last_line':num})
                                                #print("match_time: "+ match_time)
                                                self.server_status.update({'tempcount':-5})
                                                self.server_status.update({'update_embeds':True})
                                                honCMD.updateStatus_GI(self,tempData)
                                                print(f"[{match_id}] Match in progress, elapsed duration: {match_time}")
                                                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"[{match_id}] Match in progress, elapsed duration: {match_time}","INFO")
                                            break
                                        except AttributeError as e:
                                            print(e)
                                    #if "Server Skipped" in line:
                    f.close()
            return
        elif dtype == "MatchInformation":
            tempData = {}
            total_games_played_prev_int = int(self.server_status['total_games_played_prev'])
            total_games_played_now_int = int(honCMD.getData(self,"TotalGamesPlayed"))
            #print ("about to check match information")
            if (total_games_played_now_int > total_games_played_prev_int):
                #
                if self.server_status['match_log_location'] == "empty":
                    honCMD.getData(self,"getLogList_Match")

                hard_data = honCMD.compare_filesizes(self,self.server_status["match_log_location"],"match")
                soft_data = os.stat(self.server_status['match_log_location']).st_size # initial file size

                if soft_data > hard_data or 'match_log_checked' not in self.server_status:
                    print("checking match information")
                    self.server_status.update({'match_log_checked':True})
                    with open (self.server_status['match_log_location'], "r", encoding='utf-16-le') as f:
                        if self.server_status['match_info_obtained'] == False:
                            for line in f:
                                if "INFO_MATCH name:" in line:
                                    game_name = re.findall(r'"([^"]*)"', line)
                                    game_name = game_name[0]
                                    tempData.update({'game_name':game_name})
                                    honCMD.updateStatus(self,tempData)
                                    print("game_name: "+ game_name)
                                    if 'TMM' in game_name:
                                        tempData.update({'game_type':'Ranked TMM'})
                                        honCMD.updateStatus(self,tempData)
                                    else:
                                        tempData.update({'game_type':'Public Games'})
                                        honCMD.updateStatus(self,tempData)
                                if "INFO_MAP name:" in line:
                                    game_map = re.findall(r'"([^"]*)"', line)
                                    game_map = game_map[0]
                                    tempData.update({'game_map':game_map})
                                    honCMD.updateStatus(self,tempData)
                                    print("map: "+ game_map)
                                if "INFO_SETTINGS mode:" in line:
                                    game_mode = re.findall(r'"([^"]*)"', line)
                                    game_mode = game_mode[0]
                                    game_mode = game_mode.replace('Mode_','')
                                    tempData.update({'game_mode':game_mode})
                                    honCMD.updateStatus(self,tempData)
                                    print("game_mode: "+ game_mode)
                                    tempData.update({"match_info_obtained":True})
                                    tempData.update({"game_started":True})
                                    tempData.update({"first_run":False})
                                    tempData.update({"lobby_created":True})
                                    tempData.update({"tempcount":-5})
                                    tempData.update({'update_embeds':False})
                                    honCMD.updateStatus(self,tempData)
        #
        #   Get the last restart time
        elif dtype == "lastRestart":
            if exists(processed_data_dict['last_restart_loc']):
                with open(processed_data_dict['last_restart_loc'], 'r') as f:
                    last_restart = f.readline()
                f.close()
            else:
                last_restart = "not yet restarted"
                with open(processed_data_dict['last_restart_loc'], 'w') as f:
                    f.write(last_restart)
            return last_restart
        #
        #   Update the last restart time
        elif dtype == "update_last_restarted":
            t = time.localtime()
            last_restart_time = time.strftime('%b-%d-%Y %H:%M', t)
            with open (processed_data_dict['last_restart_loc'], 'w') as f:
                f.write(last_restart_time)
            return
        #
        #   Get a list of all local maps
        elif dtype == "availMaps":
            available_maps = []
            for item in os.listdir(f"{processed_data_dict['hon_directory']}game\\maps"):
                if item.endswith(".s2z"):
                    item = item.replace('.s2z','')
                    print("adding to list: "+str(item))
                    available_maps.append(item)
            return available_maps
        #
        #   Get latest match log
        elif dtype == "getLogList_Match":
            print("checking game logs")
            tempList = []
            try:
                # get list of files that matches pattern
                pattern="M*.log"
                #pattern="M*log"

                files = list(filter(os.path.isfile,glob.glob(pattern)))

                # sort by modified time
                files.sort(key=lambda x: os.path.getmtime(x))

                # get last item in list
                matchLoc = files[-1]
                matchID = matchLoc.replace(".log","")
                match_status.update({'match_id':matchID})
                self.server_status.update({"match_log_location":matchLoc})
                print("Most recent match, matching {}: {}".format(pattern,matchLoc))

                # for item in os.listdir():
                #     if "game" in item or (item.startswith("M") and item.endswith(".log")):
                #         tempList.append(item)
                # gameLoc = tempList[len(tempList)-1]
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                pass

            return True
        #
        #   Get latest game lobby logs
        elif dtype == "getLogList_Game":
            print("checking game logs")
            tempList = []
            gameLoc = None
            try:
                # get list of files that matches pattern
                #pattern=f"Slave-1_M*console.clog"
                # new world order - with slaves
                pattern=f"Slave{processed_data_dict['svr_id']}*M*console.clog"
                #pattern="M*log"

                files = list(filter(os.path.isfile,glob.glob(pattern)))

                # sort by modified time
                files.sort(key=lambda x: os.path.getmtime(x))

                # get last item in list
                gameLoc = files[-1]
                self.server_status.update({"game_log_location":gameLoc})
                match_id = re.search(r'M([0-9]+)', gameLoc)
                match_id = match_id.group(0)
                print(f"Lobby created: {match_id}")
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"Lobby created: {match_id}","INFO")
                print("Most recent file matching {}: {}".format(pattern,gameLoc))

                # for item in os.listdir():
                #     if "game" in item or (item.startswith("M") and item.endswith(".log")):
                #         tempList.append(item)
                # gameLoc = tempList[len(tempList)-1]
                return gameLoc
            except Exception:
                print(traceback.format_exc())
                honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                pass
        #
        #   Get latest server slave log
        elif dtype == "getLogList_Slave":
            print("checking slave logs")
            tempList = []
            for item in os.listdir(processed_data_dict['hon_logs_dir']):
                if (item.startswith("Slave") and item.endswith(".log")) and "Slave-1_M_console.clog" not in item and 'Slave-Temp.log' not in item: #or (item.startswith("Slave-1_M") and item.endswith("console.clog"))
                    tempList.append(item)
            if not tempList:
                # catch error where there is no slave log, create a temp one.
                print("NO SLAVE LOG. FIRST TIME BOT IS BEING LAUNCHED")
                with open(f"{processed_data_dict['hon_logs_dir']}\\Slave-Temp.log", 'w'): pass
                tempList.append("Slave-Temp.log")
            slaveLog = tempList[len(tempList)-1]
            self.server_status.update({"slave_log_location":slaveLog})
            return True

        #
        #   Get the file size of the slave log and write it to a temporary file
        elif dtype == "loadHardSlave":
            last_modified_time_file = f"{processed_data_dict['sdc_home_dir']}\\last_modified_time"
            #
            #   This reads the data if it exists
            if (exists(last_modified_time_file)):
                with open(last_modified_time_file, 'r') as last_modified:
                    lastmodData = last_modified.readline()
                last_modified.close()
                lastmodData = int(lastmodData)
                #
                #   Gets the current byte size of the slave log
                #
                # Commenting temprarily as there are issues if the match is not restarted in between games.
                if self.server_status['slave_log_location'] == "empty":
                    honCMD.getData(self,"getLogList_Slave")
                fileSize = os.stat(self.server_status['slave_log_location']).st_size
                #
                #   After reading data set temporary file to current byte size
                with open(last_modified_time_file, 'w') as last_modifiedw:
                    last_modifiedw.write(f"{fileSize}")
                last_modifiedw.close()
                return lastmodData
            #
            #   If there was no temporary file to load data from, create it.
            else:
                if self.server_status['slave_log_location'] == "empty":
                    honCMD.getData(self,"getLogList_Slave")
                try:
                    fileSize = os.stat(self.server_status['slave_log_location']).st_size
                    with open(last_modified_time_file, 'w') as last_modified:
                        last_modified.write(f"{fileSize}")
                    last_modified.close()
                except Exception:
                    print(traceback.format_exc())
                    honCMD().append_line_to_file(f"{processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                return fileSize
        #
        #    Get the real byte size of the slave log.
        elif dtype == "loadSoftSlave":
            if self.server_status['slave_log_location'] == "empty":
                    honCMD.getData(self,"getLogList_Slave")
            fileSize = os.stat(self.server_status['slave_log_location']).st_size
            return fileSize
        #
        # Come here when a lobby has been created, and the real slave log byte is different to the current byte size, and start collecting lobby information.
        elif dtype == "GameCheck":
            tempData = {}

            if self.server_status['slave_log_location'] == "empty":
                honCMD.getData(self,"getLogList_Slave")
            #softSlave = mData.getData(self,"loadSoftSlave")
            #hardSlave = mData.getData(self,"loadHardSlave")

            #if softSlave is not hardSlave: #and check_lobby is True:
            #
            #   Commenting below 3 lines due to an error with encoding. Trying to be consistent
            # dataL = open(self.server_status['slave_log_location'],encoding='utf-16-le')
            # data = dataL.readlines()
            # dataL.close()
            with open (self.server_status['slave_log_location'], "r", encoding='utf-16-le') as f:
                #
                #   Someone has connected to the server and is about to host a game
                for line in f:
                    if "Name: " in line:
                        host = line.split(": ")
                        host = host[2].replace('\n','')
                        tempData.update({'game_host':host})
                        honCMD.updateStatus(self,tempData)
                        print ("host: "+host)
                    if "Version: " in line:
                        version = line.split(": ")
                        version = version[2].replace('\n','')
                        tempData.update({'game_version':version})
                        honCMD.updateStatus(self,tempData)
                        print("version: "+version)
                    if "] IP: " in line:
                        client_ip = line.split(": ")
                        client_ip = client_ip[2].replace('\n','')
                        tempData.update({'client_ip':client_ip})
                        honCMD.updateStatus(self,tempData)
                        print(client_ip)
                    #
                    #   Arguments passed to server, and lobby starting
                    if "GAME_CMD_CREATE_GAME" in line:
                        print("lobby starting....")
                        test = line.split(' ')
                        for parameter in test:
                            if "map:" in parameter:
                                map = parameter.split(":")
                                map = map[1]
                                tempData.update({'game_map':map})
                                print("map: "+ map)
                            if "mode:" in parameter:
                                mode = parameter.split(":")
                                mode = mode[1]
                                tempData.update({'game_mode':mode})
                                print("mode: "+ mode)
                            if "teamsize:" in parameter:
                                teamsize = parameter.split(":")
                                teamsize = teamsize[1]
                                slots = int(teamsize)
                                slots *= 2
                                tempData.update({'slots':slots})
                                print("teamsize: "+ teamsize)
                                print("slots: "+ str(slots))
                            if "spectators:" in parameter:
                                spectators = parameter.split(":")
                                spectators = spectators[1]
                                spectators = int(spectators)
                                tempData.update({'spectators':spectators})
                                print("spectators: "+ str(spectators))
                            if "referees:" in parameter:
                                referees = parameter.split(":")
                                referees = referees[1]
                                referees = int(referees)
                                tempData.update({'referees':referees})
                                print("referees: "+ str(referees))
                        try:
                            total_slots = slots + spectators + referees
                        except Exception: total_slots = 10
                        #
                        #   Set firstrunthrough to false so we don't accidentally come back here and waste IO.
                        #   Also set some other booleans for code logic later on
                        self.first_run = False
                        self.just_collected = True
                        self.lobby_created = True

                        tempData.update({'first_run':self.first_run})
                        tempData.update({'just_collected':self.just_collected})
                        tempData.update({'lobby_created':self.lobby_created})
                        tempData.update({'total_slots':total_slots})
                        tempData.update({'update_embeds':True})
                        tempData.update({'tempcount':-5})

                        honCMD.updateStatus(self,tempData)
                        #self.server_status.update[{"first_run":"true"}]
                        #self.server_status.update[{'just_collected':self.just_collected}]
                        #self.server_status.update[{'lobby_created':self.lobby_created}]
                    elif "Successfully got a match ID" in line:
                        self.first_run = False
                        self.just_collected = True
                        self.lobby_created = True

                        tempData.update({'first_run':self.first_run})
                        tempData.update({'just_collected':self.just_collected})
                        tempData.update({'lobby_created':self.lobby_created})
                        honCMD.updateStatus(self,tempData)
            f.close()
            return tempData
        elif dtype == "ServerReadyCheck":
            tempData = {}
            # while True:
            if self.server_status['slave_log_location'] == "empty":
                honCMD().getData("getLogList_Slave")
            file1 = os.stat(self.server_status['slave_log_location']) # initial file size
            file1_size = file1.st_size

            # your script here that collects and writes data (increase file size)
            time.sleep(1)
            file2 = os.stat(self.server_status['slave_log_location']) # updated file size
            file2_size = file2.st_size
            comp = file2_size - file1_size # compares sizes
            if comp == 0:
                tempData.update({'server_ready':True})
                tempData.update({'tempcount':-5})
                tempData.update({'update_embeds':True})
                honCMD.updateStatus(self,tempData)
                return True
            else:
                return
                #time.sleep(5)

class Misc:
    def __init__():
        return
    def get_proc(proc_name):
        procs = []
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                procs.append(proc)
        return procs
    def check_port(port):
        command = subprocess.Popen(['netstat','-oanp','udp'],stdout=subprocess.PIPE)
        result = command.stdout.read()
        result = result.decode()
        if f"0.0.0.0:{port}" in result:
            return True
        else:
            return False
