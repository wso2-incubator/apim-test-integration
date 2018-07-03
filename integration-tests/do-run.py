# Copyright (c) 2018, WSO2 Inc. (http://wso2.com) All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# importing required modules
import sys
from xml.etree import ElementTree as ET
import subprocess
import wget
import logging
import inspect
import os
import shutil
import pymysql
import sqlparse
from pathlib import Path
import requests
import configure_product as cp
from subprocess import Popen, PIPE
from const import TEST_PLAN_PROPERTY_FILE_NAME, INFRA_PROPERTY_FILE_NAME, LOG_FILE_NAME, DB_META_DATA, \
    PRODUCT_STORAGE_DIR_NAME, DB_CARBON_DB, DB_AM_DB, DB_STAT_DB, DB_MB_DB

git_repo_url = None
git_branch = None
os_type = None
workspace = None
product_name = None
product_id = None
log_file_name = None
target_path = None
db_engine = None
db_engine_version = None
product_dist_download_api = None
sql_driver_location = None
db_host = None
db_port = None
db_username = None
db_password = None
database_config = {}


def read_proprty_files():
    global db_engine
    global db_engine_version
    global git_repo_url
    global git_branch
    global product_dist_download_api
    global sql_driver_location
    global db_host
    global db_port
    global db_username
    global db_password
    global workspace
    global product_id
    global database_config

    workspace = os.getcwd()
    property_file_paths = []
    test_plan_prop_path = Path(workspace + "/" + TEST_PLAN_PROPERTY_FILE_NAME)
    infra_prop_path = Path(workspace + "/" + INFRA_PROPERTY_FILE_NAME)

    if Path.exists(test_plan_prop_path) and Path.exists(infra_prop_path):
        property_file_paths.append(test_plan_prop_path)
        property_file_paths.append(infra_prop_path)

        for path in property_file_paths:
            with open(path, 'r') as filehandle:
                for line in filehandle:
                    if line.startswith("#"):
                            continue
                    prop = line.split("=")
                    key = prop[0]
                    val = prop[1]
                    if key == "DBEngine":
                        db_engine = val.strip()
                    elif key == "DBEngineVersion":
                        db_engine_version = val
                    elif key == "gitURL":
                        git_repo_url = val.strip().replace('\\', '')
                        product_id = git_repo_url.split("/")[-1].split('.')[0]
                    elif key == "gitBranch":
                        git_branch = val.strip()
                    elif key == "productDistDownloadApi":
                        product_dist_download_api = val.strip().replace('\\', '')
                    elif key == "sqlDriversLocationUnix" and not sys.platform.startswith('win'):
                        sql_driver_location = val.strip()
                    elif key == "sqlDriversLocationWindows" and sys.platform.startswith('win'):
                        sql_driver_location = val.strip()
                    elif key == "DatabaseHost":
                        db_host = val.strip()
                    elif key == "DatabasePort":
                        db_port = val.strip()
                    elif key == "DBUsername":
                        db_username = val.strip()
                    elif key == "DBPassword":
                        db_password = val.strip()
    else:
        raise Exception("Test Plan Property file or Infra Property file is not in the workspace: " + workspace)


def validate_property_radings():
    if None in (
    db_engine_version, git_repo_url, product_id, git_branch, product_dist_download_api, sql_driver_location, db_host,
    db_port, db_username, db_password):
        return False
    return True


def get_db_meta_data(argument):
    switcher = DB_META_DATA
    return switcher.get(argument, False)


def construct_url(prefix):
    url = prefix + db_host + ":" + db_port + "/"
    return url


def function_logger(file_level, console_level=None):
    global log_file_name
    log_file_name = LOG_FILE_NAME
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default, logs all messages
    logger.setLevel(logging.DEBUG)

    if console_level != None:
        # StreamHandler logs to console
        ch = logging.StreamHandler()
        ch.setLevel(console_level)
        ch_format = logging.Formatter('%(asctime)s - %(message)s')
        ch.setFormatter(ch_format)
        logger.addHandler(ch)

    # log in to a file
    fh = logging.FileHandler("{0}.log".format(function_name))
    fh.setLevel(file_level)
    fh_format = logging.Formatter('%(asctime)s - %(lineno)d - %(levelname)-8s - %(message)s')
    fh.setFormatter(fh_format)
    logger.addHandler(fh)

    return logger


def download_file(url, destination):
    """Download a file using wget package.
    Download the given file in _url_ as the directory+name provided in _destination_
    """
    wget.download(url, destination)


def get_db_hostname(url, db_type):
    """Retreive db hostname from jdbc url
    """
    if db_type == 'ORACLE':
        hostname= url.split(':')[3].replace("@", "")
    else:
        hostname = url.split(':')[2].replace("//", "")
    return hostname


def run_sqlserver_commands(query):
    """Run SQL_SERVER commands using sqlcmd utility.
    """
    subprocess.call(['sqlcmd', '-S', db_host, '-U', database_config['user'], '-P', database_config['password'], '-Q', query])


def get_mysql_connection(dbName=None):
    if dbName is not None:
        conn = pymysql.connect(host=get_db_hostname(database_config['url'], 'MYSQL'), user=database_config['user'],
                               passwd=database_config['password'], db=dbName)
    else:
        conn = pymysql.connect(host=get_db_hostname(database_config['url'], 'MYSQL'), user=database_config['user'],
                               passwd=database_config['password'])
    return conn


def run_mysql_commands(query):
    """Run mysql commands using mysql client when db name not provided.
    """
    conn = get_mysql_connection()
    conectr = conn.cursor()
    conectr.execute(query)
    conn.close()

def create_ora_schema_script(database):
    q = "CREATE USER {0} IDENTIFIED BY {1}; GRANT CONNECT, RESOURCE, DBA TO {0}; GRANT UNLIMITED TABLESPACE TO {0};".format(
        database, database_config["password"])
    return q

def run_oracle_commands(database):
    """Run oracle commands using sqlplus client when db name(user) is not provided.
    """
    query = create_ora_schema_script(database)
    connectString = "{0}/{1}@//{2}/{3}".format(database_config["user"], database_config["password"], 
        db_host, "ORCL")
    session = Popen(['sqlplus', '-S', connectString], stdin=PIPE, stdout=PIPE, stderr=PIPE)
    session.stdin.write(bytes(query,'utf-8'))
    return session.communicate()

def run_oracle_script(script, database):
    """Run oracle commands using sqlplus client when dbname(user) is provided.
    """
    connectString = "{0}/{1}@//{2}/{3}".format(database, database_config["password"], 
        db_host, "ORCL")
    session = Popen(['sqlplus', '-S', connectString], stdin=PIPE, stdout=PIPE, stderr=PIPE)
    session.stdin.write(bytes(script,'utf-8'))
    return session.communicate()


def run_sqlserver_script_file(db_name, script_path):
    """Run SQL_SERVER script file on a provided database.
    """
    subprocess.call(
        ['sqlcmd', '-S', db_host, '-U', database_config["user"], '-P', database_config["password"], '-d', db_name, '-i',
         script_path])


def run_mysql_script_file(db_name, script_path):
    """Run MYSQL db script file on a provided database.
    """
    conn = get_mysql_connection(db_name)
    conectr = conn.cursor()

    sql = open(script_path).read()
    sql_parts = sqlparse.split(sql)
    for sql_part in sql_parts:
        if sql_part.strip() == '':
            continue
        conectr.execute(sql_part)
    conn.close()


def copy_file(source, target):
    if sys.platform.startswith('win'):
        source = cp.winapi_path(source)
        target = cp.winapi_path(target)
        shutil.copy(source, target)
    else:
        shutil.copy(source, target)


def get_product_name(jkns_api_url):
    req_url = jkns_api_url + 'xml?xpath=/*/artifact[1]/fileName'
    headers = {'Accept': 'application/xml'}
    response = requests.get(req_url, headers=headers)
    if response.status_code == 200:
        root = ET.fromstring(response.content)
        product_name = root.text.split('-')[0] + "-" + root.text.split('-')[1]
        return product_name
    else:
        logger.infor('Failure on jenkins api call')


def get_product_dist_rel_path(jkns_api_url):
    req_url = jkns_api_url + 'xml?xpath=/*/artifact[1]/relativePath'
    headers = {'Accept': 'application/xml'}
    response = requests.get(req_url, headers=headers)
    if response.status_code == 200:
        root = ET.fromstring(response.content)
        dist_rel_path = root.text.split('wso2')[0]
        return dist_rel_path
    else:
        logger.info('Failure on jenkins api call')


def get_product_dist_arifact_path(jkns_api_url):
    artfct_path = jkns_api_url.split('/api')[0] + '/artifact/'
    return artfct_path


def setup_databases(script_path, db_names):
    """Create required databases.
    """
    for database in db_names:
        if database == DB_CARBON_DB:
            if db_engine.upper() == 'MSSQL':
                # create database
                run_sqlserver_commands('CREATE DATABASE {0}'.format(database))
                # manipulate script path
                scriptPath = script_path / 'mssql.sql'
                # run db scripts
                run_sqlserver_script_file(database, str(scriptPath))
            elif db_engine.upper() == 'MYSQL':
                scriptPath = script_path / 'mysql5.7.sql'
                # create database
                run_mysql_commands('CREATE DATABASE IF NOT EXISTS {0};'.format(database))
                # run db script
                run_mysql_script_file(database, str(scriptPath))

            elif db_engine.upper() == 'ORACLE':
                # create oracle schema
                logger.info(run_oracle_commands(database))
                # run db script
                scriptPath = script_path / 'oracle.sql'
                logger.info(run_oracle_script('@{0}'.format(str(scriptPath)), database))
        elif database == DB_AM_DB:
            if db_engine.upper() == 'MSSQL':
                # create database
                run_sqlserver_commands('CREATE DATABASE {0}'.format(database))
                # manipulate script path
                scriptPath = script_path / 'apimgt/mssql.sql'
                # run db scripts
                run_sqlserver_script_file(database, str(scriptPath))
            elif db_engine.upper() == 'MYSQL':
                scriptPath = script_path / 'apimgt/mysql5.7.sql'
                # create database
                run_mysql_commands('CREATE DATABASE IF NOT EXISTS {0};'.format(database))
                # run db script
                run_mysql_script_file(database, str(scriptPath))
            elif db_engine.upper() == 'ORACLE':
                logger.info(run_oracle_commands(database))
                # run db script
                scriptPath = script_path / 'apimgt/oracle.sql'
                logger.info(run_oracle_script('@{0}'.format(str(scriptPath)), database))
        elif database == DB_STAT_DB:
            if db_engine.upper() == 'MSSQL':
                # create database
                run_sqlserver_commands('CREATE DATABASE {0}'.format(database))
            elif db_engine.upper() == 'MYSQL':
                # create database
                run_mysql_commands('CREATE DATABASE IF NOT EXISTS {0};'.format(database))
            elif db_engine.upper() == 'ORACLE':
                #create database
                logger.info(run_oracle_commands(database))
        elif database == DB_MB_DB:
            if db_engine.upper() == 'MSSQL':
                # create database
                run_sqlserver_commands('CREATE DATABASE {0}'.format(database))
                # manipulate script path
                scriptPath = script_path / 'mb-store/mssql.sql'
                # run db scripts
                run_sqlserver_script_file(database, str(scriptPath))
            elif db_engine.upper() == 'MYSQL':
                # create database
                run_mysql_commands('CREATE DATABASE IF NOT EXISTS {0};'.format(database))
                # manipulate script path
                scriptPath = script_path / 'mb-store/mysql-mb.sql'
                # run db scripts
                run_mysql_script_file(database, str(scriptPath))
            elif db_engine.upper() == 'ORACLE':
                logger.info(run_oracle_commands(database))
                # run db script
                scriptPath = script_path / 'mb-store/oracle.sql'
                logger.info(run_oracle_script('@{0}'.format(str(scriptPath)), database))


def construct_db_config():
    db_meta_data = get_db_meta_data(db_engine.upper())
    if db_meta_data:
        database_config["driver_class_name"] = db_meta_data["driverClassName"]
        database_config["password"] = db_password
        database_config["sql_driver_location"] = sql_driver_location + "/" + db_meta_data["jarName"]
        database_config["url"] = construct_url(db_meta_data["prefix"])
        database_config["user"] = db_username
        database_config["db_engine"] = db_engine
    else:
        raise BaseException("Creating process of Database configuration is failed")


def run_integration_test():
    """Run integration tests.
    """
    integration_tests_path = Path(workspace + "/" + product_id + "/" + 'modules/integration')
    if sys.platform.startswith('win'):
        subprocess.call(['mvn', 'clean', 'install'], shell=True, cwd=integration_tests_path)
    else:
        subprocess.call(['mvn', 'clean', 'install'], cwd=integration_tests_path)
    logger.info('Integration test Running is completed.')


def main():
    try:
        global logger
        global product_name
        logger = function_logger(logging.DEBUG, logging.DEBUG)
        if sys.version_info < (3, 6):
            raise Exception(
                "To run do-run.py script you must have Python 3.6 or latest. Current version info: " + sys.version_info)
        read_proprty_files()
        if not validate_property_radings:
            raise Exception("Property filr reading error. Please verify the property file content and the format")
        construct_db_config()

        # product name retrieve from jenkins api
        product_name = get_product_name(product_dist_download_api)

        # clone the product repo
        subprocess.call(['git', 'clone', '--branch', git_branch, git_repo_url], cwd=workspace)
        logger.info('cloning repo done.')

        product_file_name = product_name + ".zip"
        dist_downl_url = get_product_dist_arifact_path(product_dist_download_api) + get_product_dist_rel_path(
            product_dist_download_api) + product_file_name

        # product download path and file name constructing
        prodct_download_dir = Path(workspace + "/" + PRODUCT_STORAGE_DIR_NAME)
        if not Path.exists(Path(workspace + "/" + PRODUCT_STORAGE_DIR_NAME)):
            Path(prodct_download_dir).mkdir(parents=True, exist_ok=True)
        prodct_file_path = prodct_download_dir / product_file_name
        # download the last released pack from Jenkins
        download_file(dist_downl_url, str(prodct_file_path))
        logger.info('downloading the pack from Jenkins done.')

        # populate databases
        script_path = Path(workspace + "/" + PRODUCT_STORAGE_DIR_NAME + "/" + product_name + "/" + 'dbscripts')
        db_names = cp.configure_product(product_name, product_id, database_config, workspace)
        if len(db_names) == 0 or db_names is None:
            raise Exception ("Failed the product configuring")
        setup_databases(script_path, db_names)
        logger.info('Database setting up is done.')
        logger.info('Starting Integration test running.')
        run_integration_test()
    except Exception as e:
        logger.error("Error occurred while running the do_run.py script", exc_info=True)
    except BaseException as e:
        logger.error("Error occurred while doing the configuration", exc_info=True)


if __name__ == "__main__":
    main()
