from datetime import datetime, timezone
from time import time
from flask import Flask, g, render_template, request, jsonify, Response
from flask_swagger import swagger
import requests
from requests_html import HTMLSession

__version__ = '0.1.0'
app = Flask(__name__)
app.config.from_pyfile("config.cfg")
try:
    CONN = pymysql.connect(host=app.config['MYSQL_DATABASE_HOST'],
                           user=app.config['MYSQL_DATABASE_USER'],
                           password=app.config['MYSQL_DATABASE_PASSWORD'],
                           db=app.config['MYSQL_DATABASE_DB'],
                           cursorclass=pymysql.cursors.DictCursor)
    CURSOR = CONN.cursor()
except Exception as err:
    ttemplate = "An exception of type {0} occurred. Arguments:\n{1!r}"
    tmessage = ttemplate.format(type(err).__name__, err.args)
    print(tmessage)
    sys.exit(-1)

# Configuration
CONFIG = {'config': {'url': app.config['CONFIG_ROOT']}}

# *****************************************************************************
# * Flask                                                                     *
# *****************************************************************************

@app.before_request
def before_request():
    ''' If needed, initilize global variables.
    '''
    # pylint: disable=W0603
    global CONFIG
    app.config['COUNTER'] += 1
    endpoint = request.endpoint if request.endpoint else '(Unknown)'
    app.config['ENDPOINTS'][endpoint] = app.config['ENDPOINTS'].get(endpoint, 0) + 1
    if 'jacs' not in CONFIG:
        data = call_responder('config', 'config/rest_services')
        CONFIG = data['config']

# *****************************************************************************
# * Web content                                                               *
# *****************************************************************************
@app.route('/')
def show_summary():
    ''' Default route
    '''
    try:
        g.c.execute("SELECT * FROM project_stats_vw")
        rows = g.c.fetchall()
    except Exception as err:
        print(err)
    arows = []
    for row in rows:
        arows.append(row)
    return render_template('home.html', urlroot=request.url_root,
                           assignmentrows=arows)
