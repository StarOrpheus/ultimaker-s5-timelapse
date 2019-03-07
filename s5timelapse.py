#!/usr/local/bin/python3
import time, json, os, sqlite3, uuid
import requests as http
import numpy as np
from os.path import isfile, join
from threading import Thread
from datetime import date, datetime

FRAMERATE = 30
TIMELAPSE_DURATION = 60
TIMELAPSE_PATH = "timelapses"
DATABASE_PATH = "timelapses.db"

# Checks if a print is running
#
# @return boolean the status of the printer
def is_printing():
	try:
		status = http.get("http://10.32.10.20/api/v1/printer/status")
		if status.json() == "printing":
			state = http.get("http://10.32.10.20/api/v1/print_job/state").json()
			if state == 'none' or state == 'wait_cleanup' or state == "wait_user_action":
				return False
			else:
				return True
		else:
			return False;
	except Exception as e:
		print(e)
		return False

# Checks if a print is starting
#
# @return boolean the status of the calibration
def is_pre_printing():
	state = http.get("http://10.32.10.20/api/v1/print_job/state").json()
	return state == 'pre_print'

# Add a timelapse in the database
#
# @return int the id of the timelapse
def register_print_start():
	db = sqlite3.connect(DATABASE_PATH)
	db_cur = db.cursor()

	title = http.get("http://10.32.10.20/api/v1/print_job/name").json()
	duration = http.get("http://10.32.10.20/api/v1/print_job/time_total").json()
	status = "printing"
	
	db_cur.execute("INSERT INTO 'timelapses' VALUES(NULL, ?, ?, ?, ?)", (title, status, duration, date.today()))
	
	db.commit()
	db.close()
	return db_cur.lastrowid

# Updates a timelapse status
#
# @param id the id of the timelapse in the db
# @param status the status to be updated
def update_timelapse_status(id, status):
	db = sqlite3.connect(DATABASE_PATH)
	db_cur = db.cursor()
	
	db_cur.execute("""
		UPDATE timelapses SET status = ? WHERE id = ?
	""", (status, id, ))
	
	db.commit()
	db.close()

# Checks if timelapses are not too old or if files are not missing
def check_timelapses():
	db = sqlite3.connect(DATABASE_PATH)
	db_cur = db.cursor()

	db_cur.execute("""
	CREATE TABLE IF NOT EXISTS timelapses(
		id INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
		title TEXT,
		status TEXT,
		duration INTEGER,
		date DATE)
	""");

	db_cur.execute("SELECT * from timelapses")
	timelapses = db_cur.fetchall()
	
	# checks if timelapse files are not missing
	for timelapse in timelapses:
		filepath = get_filepath(timelapse[0])
		if not os.path.isfile(filepath):
			update_timelapse_status(timelapse[0], "missing")

	# deletes a timelapse and its file if too old
	for timelapse in timelapses:
		timelapseDate = timelapse[4].split("-")
		timelapseDate = date(int(timelapseDate[0]), int(timelapseDate[1]), int(timelapseDate[2]))
		currentDate = date.today()
		if (currentDate - timelapseDate).days > 31:
			filepath = get_filepath(timelapse[0])
			if os.path.isfile(filepath):
				os.remove(filepath)
			db_cur.execute("DELETE FROM timelapses WHERE id = ?", (timelapse[0], ))

	db.commit()
	db.close()

# Gets the filepath of a specific timelapse
#
# @param id the id of the timelapse
def get_filepath(id):
	db = sqlite3.connect(DATABASE_PATH)
	db_cur = db.cursor()
	
	db_cur.execute("SELECT title FROM timelapses WHERE id = ?", (id, ))
	title = db_cur.fetchone()[0]
	
	db.commit()
	db.close()

	return os.path.join(TIMELAPSE_PATH, title + str(id) + ".avi")

def start_timelapse_daemon():
	while True:
		check_timelapses()

		print("Waiting for print to start...")
		while not is_printing():
			time.sleep(5)

		print("Waiting for printer calibration...")
		while is_pre_printing():
			time.sleep(1)

		print("Printing...")
		current_print_id = register_print_start()
		# removes existing tmp folder
		if os.path.isdir("tmp"):
			for file in os.listdir("tmp"):
				file_path = os.path.join("tmp", file)
				if os.path.isfile(file_path):
					os.remove(file_path)
		else:
			os.mkdir("tmp")

		duration = http.get("http://10.32.10.20/api/v1/print_job/time_total").json();
		frame = 0
		while is_printing():
			frame += 1
			res = http.get("http://10.32.10.20:8080/?action=snapshot")
			
			filepath = "tmp/" + str(frame) + ".jpg"
			f = open(filepath, 'bw')
			f.write(res.content)
			f.close()

			time.sleep(duration / (FRAMERATE * TIMELAPSE_DURATION))
		
		update_timelapse_status(current_print_id, "finished")
		# generates the video
		filepath = get_filepath(current_print_id)
		if not os.path.isdir(TIMELAPSE_PATH):
			os.mkdir(TIMELAPSE_PATH)
		ffmpegcmd = "ffmpeg -r 30 -i 'tmp/%d.jpg' -qscale 7 " + filepath 
		os.system(ffmpegcmd)
		
		# removes the tmp folder
		for file in os.listdir("tmp"):
			file_path = os.path.join("tmp", file)
			if os.path.isfile(file_path):
				os.remove(file_path)
		os.rmdir("tmp")
		print("Print done!")

timelapseDaemonThread = Thread(None, start_timelapse_daemon)
timelapseDaemonThread.start()
