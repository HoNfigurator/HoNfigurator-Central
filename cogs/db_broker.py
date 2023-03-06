from tinydb import TinyDB, Query, where
from tinydb.table import Document
from tinyrecord import transaction
import os,traceback
import json

#db = TinyDB(f"{os.environ['HONFIGURATOR_DIR']}\\config\\server_data.json")
server_db = TinyDB(f"C:\\Users\\honserver4\\Documents\\GitHub\\honfigurator-central\\config\\server_data.json")
config_db = TinyDB(f"C:\\Users\\honserver4\\Documents\\GitHub\\honfigurator-central\\config\\config_data.json")
server_tbl = server_db.table("servers")
config_tbl = config_db.table("settings")
search = Query()


gbl_config_file = f"C:\\Users\\honserver4\\Documents\\GitHub\\honfigurator-central\\config\\config_data2.json"

class GameServerConfig():
    def __init__(self):
        return    
    def create(self):
        return self.name, self.status, self.players_online
    def return_all(self):
        return server_tbl.all()
    def return_by_id(id):
        result = server_tbl.get(doc_id=id)
        return result
    def upsert_by_id(self,data,id):
        try:
            with transaction(server_tbl) as txn:
                if server_tbl.get(doc_id=id):
                    txn.update(data,doc_ids=[id])
                else:
                    server_tbl.insert(Document(data,doc_id=id))
        except Exception:
            print(traceback.format_exc())
        return
    def update_all_by_id(self,id):
        print()

class ConfigManagement():
    def __init__(self,id):
        self.id = id
    
    def global_configuration(self):
        with open(gbl_config_file, "r") as jsonfile:
            data = json.load(jsonfile)
        return data

    def local_configuration(self):
        

    def return_all(self):
        return config_tbl.all()
#with transaction(table) as tr:
    # insert a new record
    #tr.insert({'username': 'Alice'})
    # update records matching a query
    #tr.update({'invalid': True}, where('name') == 'Alice')
    # delete records
    #tr.remove(where('invalid') == True)
    # update using a function
    #tr.update(updater, where(...))
    # insert many items
    #tr.insert_multiple(documents)
class Update():
    def __init__(self): 
        return
    def update_server_db(data,doc_id):
        with transaction(server_tbl) as txn:
            if server_tbl.get(doc_id=doc_id):
                server_tbl.update(data,doc_ids=doc_id)
            else:
                txn.insert(data)
    def update_config_db(data):
        print()

class Search():
    def __init__(self):
        return
    def return_by_id(id):
        result = server_tbl.get(doc_id=id)
        return result