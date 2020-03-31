import os
import shutil
import logging
import zipfile
from datetime import datetime
from datetime import timedelta
from functools import wraps
import tarfile
from mail_config import custom_mail_password
from mail_config import custom_mail_server
from mail_config import custom_mail_username
from mail_config import custom_server_admins

import magic
from flask_mail import Mail
from flask_mail import Message
from urllib.parse import quote
from urllib.parse import unquote

from flask import Flask
from flask import flash
from flask import request
from flask import redirect
from flask import render_template
from flask import g
from flask import session
from flask import url_for
from flask import abort
from flask import send_file
from flask import make_response
from flask import jsonify
from flask import after_this_request
import flask_openid
from openid.extensions import pape
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
import pymysql.cursors
from launchpadlib.launchpad import Launchpad
import atexit

from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(filename='collect.log', level=logging.INFO, format='%(asctime)s:%(levelname)s:%(message)s')

app = Flask(__name__)
app.config['BASE_DIR'] = os.path.abspath(
    os.path.dirname(__file__)
)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1000
app.testing = False
app.config.update(
    # Gmail sender settings
    MAIL_SERVER=custom_mail_server,
    MAIL_PORT=465,
    MAIL_USE_TLS=False,
    MAIL_USE_SSL=True,
    MAIL_USERNAME=custom_mail_username,
    MAIL_PASSWORD=custom_mail_password,
    MAIL_DEFAULT_SENDER=custom_mail_username,
    SECRET_KEY='development key',
    DEBUG=True
)

mail = Mail(app)

ALLOWED_EXTENSIONS = set(['log', 'txt', 'zip', 'tar', 'tgz'])
DISALLOWED_EXTENSIONS = set(['exe', 'mp4', 'avi', 'mkv'])
ALLOWED_MIME_TYPES = set(['text/plain', 'application/x-bzip2', 'application/zip', 'application/x-gzip',
                          'application/x-tar'])
DISALLOWED_MIME_TYPES = set(['application/x-dosexec', 'application/x-msdownload'])
TARGETED_TAR_CONTENTS = set(['controller', 'storage', 'compute'])
SERVER_ADMINS = custom_server_admins
THRESHOLD = 0.8

oid = flask_openid.OpenID(app, safe_roots=[], extension_responses=[pape.Response])


def delete_old_files():
    time_before = datetime.now() - timedelta(months=6)
    with connect().cursor() as cursor:
        files_sql = "SELECT name, user_id, launchpad_id FROM files WHERE modified_date<%s;"
        cursor.execute(files_sql, (time_before,))
        files = cursor.fetchall()
        for file in files:
            os.remove(os.path.join(app.config['BASE_DIR'], 'files', file['user_id'], str(file['launchpad_id']),
                                   file['name']))
            logging.info('Outdated file deleted: {}/{}/{}'.format(file['user_id'], file['launchpad_id'], file['name']))

        sql = "DELETE FROM files WHERE modified_date<%s;"
        cursor.execute(sql, (time_before,))
        cursor.close()


def check_launchpads():
    with connect().cursor() as cursor:
        launchpads_sql = "SELECT * FROM launchpads"
        cursor.execute(launchpads_sql)
        launchpads = cursor.fetchall()
        for launchpad in launchpads:
            launchpad_info = get_launchpad_info(launchpad['id'])
            if launchpad_info[1] is True:
                sql = "DELETE FROM launchpads WHERE id=%s;"
                cursor.execute(sql, (launchpad['id'],))
            elif launchpad_info[0] != launchpad['id']:
                sql = "UPDATE launchpads SET title = %s WHERE id = %s;"
                cursor.execute(sql, (launchpad_info[0], launchpad['id'],))
        cursor.close()


def free_storage():
    with connect().cursor() as cursor:
        files_sql = "SELECT id, name, user_id, launchpad_id FROM files ORDER BY modified_date;"
        cursor.execute(files_sql)
        files = cursor.fetchall()
        for file in files:
            os.remove(os.path.join(app.config['BASE_DIR'], 'files', str(file['user_id']), str(file['launchpad_id']),
                                   file['name']))
            logging.info('Outdated file deleted: {}/{}/{}'.format(file['user_id'], file['launchpad_id'], file['name']))
            sql = "DELETE FROM files WHERE id=%s;"
            cursor.execute(sql, (file['id'],))
            if get_usage_info()[0] < THRESHOLD:
                break
        cursor.close()


def send_weekly_reports():
    usage_info = get_usage_info()
    subject = 'Weekly Report'
    rounded_usage = round(usage_info[0], 4)
    free_space = round(usage_info[1]/1000000, 2)
    with connect().cursor() as cursor:
        sql = 'SELECT n.name, i.upload_count, i.total_size FROM openid_users n RIGHT JOIN ' \
              '(SELECT user_id, COUNT(*) AS upload_count, ROUND(SUM(file_size)/1000000, 2) AS total_size FROM files ' \
              'WHERE modified_date > NOW() - INTERVAL 1 WEEK GROUP BY user_id)i ' \
              'ON n.id = i.user_id;'
        cursor.execute(sql)
        reports_by_user = cursor.fetchall()
    reports_by_user_table = '<table><tr>' \
                            '<th>Name</th>' \
                            '<th>Number of Uploads</th>' \
                            '<th>Total Upload Size</th>' \
                            '</tr>'
    for report in reports_by_user:
        reports_by_user_table = reports_by_user_table + '<tr>' \
                                                        '<td>%s</td><td>%s</td><td>%s</td>' \
                                                        '</tr>' % (report["name"], report["upload_count"], report["total_size"])
    reports_by_user_table = reports_by_user_table + '</tr></table>'
    with app.app_context():
        for admin in SERVER_ADMINS:
            html_body = '<p>Hello %s,' \
                        '<br>Here is the upload report for last week:<br>%s' \
                        '<br>There are %s space used and %s MB of space left.' \
                        % (admin["name"], reports_by_user_table, rounded_usage, usage_info[0])

            msg = Message(subject,
                          html=html_body,
                          recipients=[admin['email']])
            mail.send(msg)


# @app.route('/storage_full/')
def if_storage_full():
    usage_info = get_usage_info()
    if usage_info[0] > THRESHOLD:
        subject = 'Storage is Nearly Full'
        rounded_usage = round(usage_info[0], 4)
        with app.app_context():
            for admin in SERVER_ADMINS:
                html_body = '<p>Hello %s,' \
                            '<br>The logfiles uploaded took %s of the server\'s total disk space.' \
                            'Oldest files will be deleted to free space.</p>' % (admin["name"], rounded_usage)

                msg = Message(subject,
                              html=html_body,
                              recipients=[admin['email']])
                mail.send(msg)
        free_storage()

        # with smtplib.SMTP('mail.wrs.com', 587) as smtp:
        #     # smtp.ehlo()
        #     smtp.starttls()
        #     smtp.ehlo()
        #
        #     # smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        #     smtp.login('Nathan.Chen@windriver.com', 'MyPassword')
        #
        #     subject = 'Storage is full'
        #     body = 'Do something'
        #
        #     msg = f'Subject: {subject}\n\n{body}'
        #
        #     smtp.sendmail('Nathan.Chen@windriver.com', 'wrcollecttesting1@gmail.com', msg)


scheduler = BackgroundScheduler()
scheduler.add_job(func=delete_old_files, trigger="cron", day='1')
scheduler.add_job(func=check_launchpads, trigger="cron", day_of_week='mon-fri')
scheduler.add_job(func=if_storage_full, trigger="cron", minute='00')
scheduler.add_job(func=send_weekly_reports, trigger="cron", day_of_week='mon')
scheduler.start()

atexit.register(lambda: scheduler.shutdown())


# @app.route('/usage/')
def get_usage_info():
    # return str(shutil.disk_usage(app.config['BASE_DIR']))
    # return str(shutil.disk_usage(os.path.join(app.config['BASE_DIR'], 'files')).used)
    # return str(shutil.disk_usage(os.path.join(app.config['BASE_DIR'], 'files')))
    disk_usage_info = shutil.disk_usage(os.path.join(app.config['BASE_DIR'], 'files'))
    usage_perc = disk_usage_info.used/disk_usage_info.total
    return [usage_perc, disk_usage_info.free]
    # return str(usage_perc)


def is_allowed(filename):
    return '.' in filename and (filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS
                                or filename.rsplit('.', 2)[1] == 'tar') \
           and filename.rsplit('.', 1)[1] not in DISALLOWED_EXTENSIONS


def get_size(fobj):
    if fobj.content_length:
        return fobj.content_length

    try:
        pos = fobj.tell()
        fobj.seek(0, 2)  # seek to end
        size = fobj.tell()
        fobj.seek(pos)  # back to original position
        return size
    except (AttributeError, IOError):
        pass

    # in-memory file object that doesn't support seeking or tell
    return 0  # assume small enough


def connect():
    return pymysql.connect(host='db',
                           user='root',
                           password='Wind2019',
                           db='collect',
                           charset='utf8mb4',
                           cursorclass=pymysql.cursors.DictCursor,
                           autocommit=True)


def confirmation_required(desc_fn):
    def inner(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.args.get('confirm') != '1':
                desc = desc_fn()
                return redirect(url_for('confirm', desc=desc, action_url=quote(request.url)))
            return f(*args, **kwargs)

        return wrapper

    return inner


def get_launchpad_info(lp):
    lp_id = lp
    if isinstance(lp, dict):
        lp_id = int(lp['launchpad_id'])
    cachedir = os.path.join(app.config['BASE_DIR'], '.launchpadlib/cache/')
    launchpad = Launchpad.login_anonymously('just testing', 'production', cachedir, version='devel')
    try:
        bug_one = launchpad.bugs[lp_id]
        # return str(type(bug_one))
        # return bug_one.bug_tasks.entries[0]['title']
        is_starlingx = any(entry['bug_target_name'] == 'starlingx' for entry in bug_one.bug_tasks.entries)
        if not is_starlingx:
            return 'You need to choose a valid StarlingX Launchpad'
        closed = all(entry['date_closed'] is not None for entry in bug_one.bug_tasks.entries)
        return [bug_one.title, closed]
    except KeyError:
        return 'Launchpad bug id does not exist'


@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def error413(e):
    # flash(u'Error: File size exceeds the 16GB limit')
    # return render_template('index.html'), 413
    # return render_template('413.html'), 413
    return 'File Too Large', 413


@app.errorhandler(401)
def error401(e):
    flash(u'Error: You are not logged in')
    return redirect(url_for('login', next=oid.get_next_url()))


@app.route('/confirm')
def confirm():
    desc = request.args['desc']
    action_url = unquote(request.args['action_url'])

    return render_template('_confirm.html', desc=desc, action_url=action_url)


def confirm_delete_profile():
    return "Are you sure you want to delete your profile? All your files will be removed."


def confirm_delete_file():
    return "Are you sure you want to delete this file?"


@app.before_request
def before_request():
    g.user = None
    g.connection = connect()
    if 'openid' in session:
        with g.connection.cursor() as cursor:
            sql = "select * from openid_users where openid = %s;"
            cursor.execute(sql, (session['openid'],))
            g.user = cursor.fetchone()
            cursor.close()


@app.after_request
def after_request(response):
    return response


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login/', methods=['GET', 'POST'])
@oid.loginhandler
def login():
    if g.user is not None:
        return redirect(oid.get_next_url())
    if request.method == 'POST':
        openid = "https://launchpad.net/~" + request.form.get('openid')
        if openid:
            pape_req = pape.Request([])
            return oid.try_login(openid, ask_for=['email', 'nickname'],
                                 ask_for_optional=['fullname'],
                                 extensions=[pape_req])
    return render_template('login.html', next=oid.get_next_url(),
                           error=oid.fetch_error())


@oid.after_login
def create_or_login(resp):
    """This is called when login with OpenID succeeded and it's not
    necessary to figure out if this is the users's first login or not.
    This function has to redirect otherwise the user will be presented
    with a terrible URL which we certainly don't want.
    """
    session['openid'] = resp.identity_url
    if 'pape' in resp.extensions:
        pape_resp = resp.extensions['pape']
        session['auth_time'] = pape_resp.auth_time
    with g.connection.cursor() as cursor:
        sql = "select * from openid_users where openid = %s;"
        cursor.execute(sql, (resp.identity_url,))
        user = cursor.fetchone()
        cursor.close()
    # user = User.query.filter_by(openid=resp.identity_url).first()
    if user is not None:
        flash(u'Successfully signed in')
        g.user = user
        return redirect(oid.get_next_url())
    return redirect(url_for('create_profile', next=oid.get_next_url(),
                            name=resp.fullname or resp.nickname,
                            email=resp.email))


@app.route('/create-profile/', methods=['GET', 'POST'])
def create_profile():
    """If this is the user's first login, the create_or_login function
    will redirect here so that the user can set up his profile.
    """
    if g.user is not None or 'openid' not in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        if not name:
            flash(u'Error: you have to provide a name')
        elif '@' not in email:
            flash(u'Error: you have to enter a valid email address')
        else:
            flash(u'Profile successfully created')
            with g.connection.cursor() as cursor:
                sql = "INSERT INTO openid_users (name, email, openid) VALUES (%s, %s, %s);"
                cursor.execute(sql, (name, email, session['openid'],))
                sql = "SELECT id FROM openid_users WHERE openid = %s;"
                cursor.execute(sql, (session['openid'],))
                user_id = cursor.fetchone()['id']
                _dir = os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(user_id))
                os.mkdir(_dir)
                cursor.close()
                return redirect(oid.get_next_url())
    return render_template('create_profile.html', next_url=oid.get_next_url())


@app.route('/profile/', methods=['GET', 'POST'])
def edit_profile():
    """Updates a profile"""
    if g.user is None:
        abort(401)
    # form = dict(name=g.user.name, email=g.user.email)
    # g_user_name = g.user.name
    # g_user_email = g.user.email
    form = {'name': g.user['name'], 'email': g.user['email']}
    # form = {'name': 1, 'email': 1}
    # form['name'] = g.user.name
    # form['email'] = g.user.email
    if request.method == 'POST':
        if 'delete' in request.form:
            with g.connection.cursor() as cursor:
                sql = "DELETE FROM openid_users WHERE openid=%s;"
                cursor.execute(sql, (session['openid'],))
                cursor.close()
                shutil.rmtree(os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(g.user['id'])))
                return redirect(oid.get_next_url())
            session['openid'] = None
            flash(u'Profile deleted')
            return redirect(url_for('index'))
        form['name'] = request.form['name']
        form['email'] = request.form['email']
        if not form['name']:
            flash(u'Error: you have to provide a name')
        elif '@' not in form['email']:
            flash(u'Error: you have to enter a valid email address')
        else:
            flash(u'Profile successfully created')
            g.user['name'] = form['name']
            g.user['email'] = form['email']
            with g.connection.cursor() as cursor:
                sql = "UPDATE openid_users SET name = %s, email = %s WHERE id = %s;"
                cursor.execute(sql, (g.user['name'], g.user['email'], g.user['id'],))
                cursor.close()
                return redirect(oid.get_next_url())
            # db_session.commit()
            # return redirect(url_for('edit_profile'))
    return render_template('edit_profile.html', form=form)


@app.route('/logout/')
def logout():
    session.pop('openid', None)
    flash(u'You have been signed out')
    return redirect(oid.get_next_url())


@app.route('/check_launchpad/<launchpad_id>', methods=['GET', 'POST'])
def check_launchpad(launchpad_id):
    with g.connection.cursor() as cursor:
        sql = "SELECT * FROM launchpads WHERE id = %s;"
        cursor.execute(sql, (launchpad_id,))
        launchpad_info = cursor.fetchone()
        if launchpad_info:
            launchpad_title = launchpad_info["title"]
        else:
            try:
                launchpad_info = get_launchpad_info(int(launchpad_id))
            except ValueError:
                res = make_response("Error: Launchpad bug id does not exist", 400)
                return res
            if launchpad_info == 'Launchpad bug id does not exist':
                res = make_response("Error: Launchpad bug id does not exist", 400)
                return res
            elif launchpad_info == 'You need to choose a valid StarlingX Launchpad':
                res = make_response("Error: You need to choose a valid StarlingX Launchpad", 400)
                return res
            elif launchpad_info[1] is True:
                res = make_response("Error: Launchpad bug is closed", 400)
                return res
            sql = "INSERT INTO launchpads (id, title) VALUES (%s, %s);"
            cursor.execute(sql, (launchpad_id, launchpad_info[0],))
            launchpad_title = launchpad_info[0]
        res = make_response(launchpad_title, 200)
        return res


@app.route('/upload/', methods=['GET', 'POST'])
def upload():
    try:
        if g.user is None:
            abort(401)
        if request.method == 'POST':
            launchpad_id = request.args.get('launchpad_id')
            if launchpad_id == '':
                res = make_response(jsonify({"message": "Error: you did not supply a valid Launchpad ID"}), 400)
                return res
            launchpad_info = 0

            # with g.connection.cursor() as cursor:
            #     sql = "SELECT id FROM launchpads WHERE id = %s;"
            #     cursor.execute(sql, (launchpad_id,))
            #     if not cursor.fetchone():
            #         try:
            #             launchpad_info = get_launchpad_info(int(launchpad_id))
            #         except ValueError:
            #             res = make_response(jsonify({"message": "Error: Launchpad bug id does not exist"}), 400)
            #             return res
            #         if launchpad_info == 'Launchpad bug id does not exist' or launchpad_info[1] is True:
            #             res = make_response(jsonify({"message": "Error: Launchpad bug id does not exist"}), 400)
            #             return res
            #         sql = "INSERT INTO launchpads (id, title) VALUES (%s, %s);"
            #         cursor.execute(sql, (launchpad_id, launchpad_info[0],))

            # file_list = request.files.getlist('file')
            # file_list = request.files['file']
            # file_list = request.files.get('file[]')
            #
            # res = make_response(jsonify({"message": str(file_list)}), 200)
            # return res

            # file_size = get_size(f)
            # if file_size > MAX_CONTENT_LENGTH:
            #     flash(u'Error: File size exceeds the 10GB limit')
            #     return redirect(oid.get_next_url())
            # for f in file_list:
            f = request.files['file']
            if f and is_allowed(f.filename):
                _launchpad_dir = os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(g.user['id']), launchpad_id)
                conflict = request.args.get('conflict')
                final_filename = secure_filename(f.filename)
                if conflict == '1':
                    if final_filename.rsplit('.', 2)[1] == 'tar' and len(final_filename.rsplit('.', 2)) == 3:
                        tail = 1
                        while True:
                            new_filename = final_filename.rsplit('.', 2)[0] + "_" + str(tail) + '.' \
                                + final_filename.rsplit('.', 2)[1] + '.' + final_filename.rsplit('.', 2)[2]
                            with g.connection.cursor() as cursor:
                                file_name_sql = "SELECT id FROM files WHERE launchpad_id=%s AND name=%s AND user_id=%s;"
                                cursor.execute(file_name_sql, (launchpad_id, new_filename, g.user['id']))
                                if cursor.fetchone():
                                    tail = tail + 1
                                else:
                                    break
                    else:
                        tail = 1
                        while True:
                            new_filename = final_filename.rsplit('.', 1)[0] + "_" + str(tail) + '.' \
                                + final_filename.rsplit('.', 1)[1]
                            with g.connection.cursor() as cursor:
                                file_name_sql = "SELECT id FROM files WHERE launchpad_id=%s AND name=%s AND user_id=%s;"
                                cursor.execute(file_name_sql, (launchpad_id, new_filename, g.user['id']))
                                if cursor.fetchone():
                                    tail = tail + 1
                                else:
                                    break
                    final_filename = new_filename
                if not os.path.isdir(_launchpad_dir):
                    os.mkdir(_launchpad_dir)
                _full_dir = os.path.join(_launchpad_dir, final_filename)
                f.save(_full_dir)
                file_size = os.stat(_full_dir).st_size
                # mimetype = f.mimetype
                # flash(mimetype)
                mime = magic.Magic(mime=True)
                mimetype = mime.from_file(_full_dir)
                if mimetype.startswith('image/', 0) or mimetype.startswith('video/', 0)\
                        or mimetype in DISALLOWED_MIME_TYPES:
                    os.remove(_full_dir)
                    res = make_response(jsonify({
                        "message": "Error: you did not supply a valid file in your request"}), 400)
                    return res
                if mimetype in ['application/x-gzip', 'application/x-tar']:
                    tar = tarfile.open(_full_dir)
                    if not any((any(x in y for x in TARGETED_TAR_CONTENTS) for y in tar.getnames())):
                        res = make_response(jsonify({
                            "message": "Error: you did not supply a valid collect file in your request"}), 400)
                        logging.info(tar.getnames())
                        return res
                if conflict == '0':
                    with g.connection.cursor() as cursor:
                        sql = "UPDATE files SET modified_date = %s, file_size = %s " \
                              "WHERE user_id = %s AND name = %s AND launchpad_id = %s;"
                        cursor.execute(
                            sql, (datetime.now(), file_size, g.user['id'], final_filename, launchpad_id))
                        cursor.close()
                    logging.info('User#{} re-uploaded file {} under launchpad bug#{}'.
                                 format(g.user['id'], final_filename, launchpad_id))
                else:
                    with g.connection.cursor() as cursor:
                        sql = "INSERT INTO files (name, user_id, launchpad_id, modified_date, file_size)" \
                              "VALUES (%s, %s, %s, %s, %s);"
                        cursor.execute(sql, (final_filename, g.user['id'], launchpad_id, datetime.now(),
                                             file_size,))
                        cursor.close()
                    logging.info('User#{} uploaded file {} under launchpad bug#{}'.
                                 format(g.user['id'], final_filename, launchpad_id))
            else:
                logging.error('User#{} tried to upload a file with invalid format'.format(g.user['id']))
                res = make_response(jsonify({"message": "Error: you did not supply a valid file in your request"}), 400)
                return res
            # except RequestEntityTooLarge:
            #     flash(u'Error: File size exceeds the 16GB limit')
            #     return redirect(oid.get_next_url())
            res = make_response(jsonify({"message": "file uploaded successfully: {}".format(f.filename)}), 200)
            return res
        return render_template('upload.html')
    except RequestEntityTooLarge:
        flash(u'Error: File size exceeds the 10GB limit')
        return redirect(oid.get_next_url())


@app.route('/user_files/', methods=['GET', 'POST'])
def list_user_files():
    """Updates a profile"""
    if g.user is None:
        abort(401)
    user_files = []
    if request.method == 'GET':
        with g.connection.cursor() as cursor:
            search = request.args.get('search')
            if search:
                sql = "SELECT f.*, l.title FROM files f JOIN launchpads l ON f.launchpad_id = l.id " \
                      "WHERE (launchpad_id = '{}' OR title LIKE '%{}%') AND user_id = {} " \
                      "ORDER BY launchpad_id DESC, f.name;".format(search, search, g.user['id'])
            # sql = "SELECT * FROM launchpads WHERE id IN (SELECT DISTINCT launchpad_id FROM files WHERE user_id = %s);"
                cursor.execute(sql,)
            else:
                sql = "SELECT f.*, l.title FROM files f JOIN launchpads l ON f.launchpad_id = l.id " \
                      "WHERE user_id = %s ORDER BY launchpad_id DESC;"
                cursor.execute(sql, (g.user['id'],))
            user_files = cursor.fetchall()
            cursor.close()
    return render_template('user_files.html', user_files=user_files)


@app.route('/public_files/', methods=['GET', 'POST'])
def list_public_files():
    """Updates a profile"""
    if g.user is None:
        abort(401)
    files = []
    if request.method == 'GET':
        with g.connection.cursor() as cursor:
            sql = "SELECT f.*, l.title, f.user_id, u.name AS user_name FROM files f JOIN launchpads l " \
                  "ON f.launchpad_id = l.id JOIN openid_users u ON f.user_id = u.id;"
            cursor.execute(sql)
            files = cursor.fetchall()
            cursor.close()
        # if files:
        #     files = list(map(lambda f: f.update({'editable': (f['user_id'] == g.user)})))
    return render_template('public_files.html', public_files=files)


@app.route('/launchpads/', methods=['GET', 'POST'])
def list_all_launchpads():
    """Updates a profile"""
    if g.user is None:
        abort(401)
    if request.method == 'GET':
        with g.connection.cursor() as cursor:
            search = request.args.get('search')
            if search:
                sql = "SELECT * FROM launchpads WHERE (id = '{}' OR title LIKE '%{}%') " \
                      "AND id IN (SELECT DISTINCT launchpad_id FROM files) ORDER BY id DESC;".format(search, search)
            # sql = "SELECT * FROM launchpads WHERE id IN (SELECT DISTINCT launchpad_id FROM files WHERE user_id = %s);"
                cursor.execute(sql,)
            else:
                sql = "SELECT * FROM launchpads WHERE id IN (SELECT DISTINCT launchpad_id FROM files) ORDER BY id DESC;"
                cursor.execute(sql,)
            user_launchpads = cursor.fetchall()
            cursor.close()
    return render_template('launchpads.html', user_launchpads=user_launchpads)


@app.route('/launchpad/<launchpad_id>', methods=['GET', 'POST'])
def list_files_under_a_launchpad(launchpad_id):
    """Updates a profile"""
    if g.user is None:
        abort(401)
    if request.method == 'GET':
        with g.connection.cursor() as cursor:
            sql = "SELECT f.*, u.name AS user_name FROM files f " \
                  "JOIN openid_users u ON f.user_id = u.id WHERE launchpad_id = %s;"
            cursor.execute(sql, (launchpad_id,))
            launchpad_files = cursor.fetchall()
            sql = "SELECT * FROM launchpads WHERE id = %s;"
            cursor.execute(sql, (launchpad_id,))
            launchpad_info = cursor.fetchone()
            cursor.close()
    return render_template('launchpad.html', launchpad_files=launchpad_files, launchpad_info=launchpad_info)
    # return render_template('user_files.html', user_launchpads=user_launchpads)


@app.route('/edit_file/<file_id>', methods=['GET', 'POST'])
def edit_file(file_id):
    """Updates a profile"""
    if g.user is None:
        abort(401)
    with g.connection.cursor() as cursor:
        sql = "SELECT * FROM files WHERE id = %s;"
        cursor.execute(sql, (file_id,))
        user_files = cursor.fetchone()
        form = {'name': user_files['name'], 'launchpad_id': user_files['launchpad_id']}
        old_form = form.copy()
        cursor.close()
    if request.method == 'POST':
        form['name'] = request.form['name']
        form['launchpad_id'] = request.form['launchpad_id']
        if not form['name']:
            flash(u'Error: you have to provide a name')
        else:
            # _dir = os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(g.user['id']))
            # flash(os.path.join(_dir, old_form['launchpad_id'], old_form['name']))
            if old_form['name'] != form['name'] or old_form['launchpad_id'] != int(form['launchpad_id']):
                _dir = os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(g.user['id']))
                _new_dir = os.path.join(_dir, str(form['launchpad_id']))
                if old_form['launchpad_id'] != form['launchpad_id']:
                    with g.connection.cursor() as cursor:
                        sql = "SELECT * FROM launchpads WHERE id = %s;"
                        cursor.execute(sql, (form['launchpad_id'],))
                        launchpad_info = cursor.fetchone()
                        if not launchpad_info:
                            try:
                                launchpad_info = get_launchpad_info(int(form['launchpad_id']))
                            except ValueError:
                                res = make_response("Error: Launchpad bug id does not exist", 400)
                                return res
                            if launchpad_info == 'Launchpad bug id does not exist':
                                flash(u'Error: Launchpad bug id does not exist')
                                return redirect(oid.get_next_url())
                            elif launchpad_info == 'You need to choose a valid StarlingX Launchpad':
                                flash(u'Error: You need to choose a valid StarlingX Launchpad')
                                return redirect(oid.get_next_url())
                            elif launchpad_info[1] is True:
                                flash(u'Error: Launchpad bug is closed')
                                return redirect(oid.get_next_url())
                            else:
                                sql = "INSERT INTO launchpads (id, title) VALUES (%s, %s);"
                                cursor.execute(sql, (form['launchpad_id'], launchpad_info[0],))
                                cursor.close()
                            if not os.path.isdir(_new_dir):
                                os.mkdir(_new_dir)
                os.rename(os.path.join(_dir, str(old_form['launchpad_id']), old_form['name']),
                          os.path.join(_dir, str(form['launchpad_id']), form['name']))
                if old_form['name'] == form['name']:
                    logging.info('User#{} changed file {}/{} to {}/{}'.
                                 format(g.user['id'], old_form['launchpad_id'],
                                        old_form['name'], form['launchpad_id'], form['name']))
            with g.connection.cursor() as cursor:
                sql = "UPDATE files SET name = %s, launchpad_id = %s, modified_date = %s WHERE id = %s;"
                cursor.execute(sql, (form['name'], form['launchpad_id'], datetime.now(), file_id,))
                cursor.close()
            flash(u'File information successfully updated')
            return redirect(url_for('edit_file', file_id=file_id, form=form))
    return render_template('edit_file.html', file_id=file_id, form=form)


@app.route('/delete_file', methods=['GET', 'POST'])
# @confirmation_required(confirm_delete_file)
def delete_file():
    """Updates a profile"""
    if g.user is None:
        abort(401)
    file_id = request.form['id']
    with g.connection.cursor() as cursor:
        file_name_sql = "SELECT name, launchpad_id FROM files WHERE id=%s;"
        cursor.execute(file_name_sql, (file_id,))
        file_info = cursor.fetchone()
        os.remove(os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(g.user['id']), str(file_info['launchpad_id']),
                               file_info['name']))

        sql = "DELETE FROM files WHERE id=%s;"
        cursor.execute(sql, (file_id,))
        cursor.close()
        logging.info('User#{} deleted file {} under launchpad bug#{}'.
                     format(g.user['id'], secure_filename(file_info['name']), file_info['launchpad_id']))
        flash(u'File deleted')
    return redirect(url_for('list_user_files'))


@app.route('/download_file/<file_id>', methods=['GET', 'POST'])
def download_file(file_id):
    with g.connection.cursor() as cursor:
        file_name_sql = "SELECT name, launchpad_id, user_id FROM files WHERE id=%s;"
        cursor.execute(file_name_sql, (file_id,))
        file_info = cursor.fetchone()
        download_link = os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(file_info['user_id']),
                                     str(file_info['launchpad_id']), file_info['name'])
        cursor.close()
        return send_file(download_link, attachment_filename=file_info['name'], as_attachment=True, cache_timeout=0)


@app.route('/download_launchpad/<launchpad_id>', methods=['GET', 'POST'])
def download_launchpad(launchpad_id):
    zipf = zipfile.ZipFile('{}.zip'.format(launchpad_id), 'w', zipfile.ZIP_DEFLATED)
    with g.connection.cursor() as cursor:
        launchpad_file_sql = "SELECT f.name, f.user_id, f.launchpad_id, u.name AS uploader FROM files f " \
                             "JOIN openid_users u ON f.user_id = u.id WHERE launchpad_id=%s;"
        cursor.execute(launchpad_file_sql, (launchpad_id,))
        files = cursor.fetchall()
        for file in files:
            zipf.write(os.path.join(app.config['BASE_DIR'], 'files/{}/'.format(file['user_id']),
                                    str(file['launchpad_id']), file['name']),
                       os.path.join(file['uploader'], file['name']))
            cursor.close()
        zipf.close()

        @after_this_request
        def remove_file(response):
            try:
                file_path = '{}.zip'.format(launchpad_id)
                os.remove(file_path)
                file_handle = open(file_path, 'r')
                file_handle.close()
            except Exception as error:
                app.logger.error("Error removing or closing downloaded file handle", error)
            return response
        return send_file('{}.zip'.format(launchpad_id), mimetype='zip',
                         attachment_filename='{}.zip'.format(launchpad_id), as_attachment=True, cache_timeout=0)


@app.route('/file_exists/', methods=['GET', 'POST'])
def file_exists():
    file_name = request.args.get('file_name')
    launchpad_id = request.args.get('launchpad_id')
    if not is_allowed(file_name):
        return '-1'
    with g.connection.cursor() as cursor:
        file_name_sql = "SELECT id FROM files WHERE launchpad_id=%s AND name=%s AND user_id=%s;"
        cursor.execute(file_name_sql, (launchpad_id, secure_filename(file_name), g.user['id']))
        if cursor.fetchone():
            return '1'
        else:
            return '0'


@app.route('/view_log/', methods=['GET', 'POST'])
def view_log():
    return send_file('collect.log', mimetype='text/plain')


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')
