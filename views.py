import os
from datetime import date
import logging

from django.db import connection
from django.conf import settings
from django.http import HttpResponse
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render_to_response
from django.template import RequestContext

# only super users should be able to import / export data
from django.contrib.admin.views.decorators import staff_member_required


# view showing all links
@staff_member_required
def importexport_index(request):

    return render_to_response('list-links.html')


# main view for exporting the database
@staff_member_required
def export_database(request):
    """
    Dump database as attachment
    
    """
    if request.method == 'POST':

        # I tried to write back the modified settings to a "settings" variable
        # but I always got an error about unbound variables. Since I couldn't fix
        # it, I'm assigning a new variable here.
        config_ok, new_settings = db_check(settings)
        if config_ok == 0:
            raise ImproperlyConfigured, "Only mysql is supported so far."

        return dump_database(new_settings)

    return render_to_response('export.html', {'action_name': 'Export Database', }, context_instance=RequestContext(request))

################################################################################

@staff_member_required
def export_media(request):
    """
    Tar the MEDIA_ROOT and send it directly to the browser
    
    """
    if request.method == 'POST':
        stdin, stdout = os.popen2('tar -cf - %s' % settings.MEDIA_ROOT)
        stdin.close()
        response = HttpResponse(stdout, mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s' % date.today().__str__()+'_media.tar'
        return response
    return render_to_response('export.html', {'action_name': 'Export Media Root',}, context_instance=RequestContext(request))


## Import Form #################################################################

from django import forms

class UploadFileForm(forms.Form):
    file  = forms.FileField()


## Import View & necessary functions ###########################################
@staff_member_required
def import_database(request):
    """
    Import database from the browser upload
    
    """

    if request.method == 'POST':

        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            handle_uploaded_file(request.FILES['file'], settings)
            return render_to_response('import_done.html', {'action_name': 'Import Database',}, context_instance=RequestContext(request))

    else:

        config_ok, new_settings = db_check(settings)
        if config_ok == 0:
            raise ImproperlyConfigured, "Only mysql is supported so far."

        form = UploadFileForm()

    return render_to_response('import.html', 
        {'form': form, 'action_name': 'Import Database',}, 
        context_instance=RequestContext(request))


## general helper functions ####################################################

def db_check(local_settings):

    config_ok = 0

    # I only tested mysql
    if local_settings.DATABASES['default']['ENGINE'] == 'mysql' or local_settings.DATABASES['default']['ENGINE'] == 'django.db.backends.mysql':
        config_ok = 1

        # replace default empty string by localhost - otherwise mysqldump
        # gives us an error
        if local_settings.DATABASES['default']['HOST'] is '':
            local_settings.DATABASES['default']['HOST'] = 'localhost'

        

    return config_ok, local_settings


################################################################################

def handle_uploaded_file(f, local_settings):

    try:
        import bz2

        # prepare data for raw mysql execution
        data = f.read()
        plain_data = bz2.decompress(data)
        # see http://code.djangoproject.com/ticket/9055
        plain_data = plain_data.replace('%', '%%')
       
        logging.debug('Starting database import ... ')
       
        # delete all tables in database
        flush_db_tables(local_settings.DATABASES['default']['NAME'])

        # recreate all tables
        from django.core import management 
        management.call_command('syncdb', interactive=False)

        ### start - import all data
        try:

            cursor = create_cursor()
            # disable foreign key checking, in order to prevent the following error:
            # 'Cannot delete or update a parent row: a foreign key constraint fails' 
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
            cursor.execute(plain_data)
            close_cursor(cursor)

            # I've closed the cursor and will open a new one, in order to prevent 
            # the following error:
            # 'Commands out of sync; you can't run this command now'
            cursor = create_cursor()
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')
            close_cursor(cursor)

                
            logging.debug('... Finished import successfully.')
            print '\t ... Finished import successfully.'
            
        except Exception, details:
            # recreate all tables in case of error - we don't want to end up with
            # missing tables.
            management.call_command('syncdb', interactive=False)
            logging.debug('\t error while importing data: %s' % details)
            print '\t error while importing data: %s' % details
            raise
        ### end - import all data

    except:
        return HttpResponse("Ups, something went wrong. You are probably missing 'bz2'.")        

################################################################################

def flush_db_tables(database_name):

    try:

        cursor = create_cursor()

        # we drop and re-create the database, since the permissions will not be affected.
        cursor.execute("drop database %s" % database_name)
        cursor.execute("create database %s" % database_name)

        close_cursor(cursor)

    except Exception, details:
        logging.debug('error while dropping and re-creating database: %s' % details)
        raise


################################################################################

def dump_database(local_settings):

    try:
        # do the sql dump
        DUMP_CMD = '%s -h %s --opt --compact --add-drop-table --skip-add-locks -u %s -p%s %s'

        cmd = DUMP_CMD % (local_settings.MYSQLDUMP, local_settings.DATABASES['default']['HOST'], local_settings.DATABASES['default']['USER'], local_settings.DATABASES['default']['PASSWORD'], local_settings.DATABASES['default']['NAME'])

        stdin, stdout = os.popen2(cmd)
        stdin.close()

        # now compress the data to bzip2
        import bz2
        data = stdout.read()
        compressed_data = bz2.compress(data)
    
        # create the response in form of an attachment
        response = HttpResponse(compressed_data, mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s' % 'django_' + date.today().__str__()+'_db.sql.bz2'

        return response
    except:
        return HttpResponse("Ups, something went wrong. You are probably missing 'bz2'.")
    

def create_cursor():
    return connection.cursor()


def close_cursor(cursor):
    if cursor:
        cursor.close()
        connection.close()


