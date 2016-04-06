PLUGIN = {
    'name': 'S3 Bucket Watch',
    'type': 's3_bucket_watch',
    'user': 's3bucketwatch',
    'password': 's3bucketwatch',
    'checkeveryxseconds': 10.0
}

###########
# Options #
###########

# Define the name of the S3 bucket we're working with.
BucketName = 'datasift-girder-test'

# Define the Girder folder ID we're working with.
gcFolderId = '5702c721d199ae38cf41479d'

# Define the local file path for downloaded files from S3 bucket.
fileBasePath = '/tmp/'

###########
# Imports #
###########

# Girder utilities.
from girder import events
from girder.plugins.jobs.constants import JobStatus
from girder.utility.model_importer import ModelImporter

# S3, Girder, OS interop.
import boto3
import girder_client
import os

# For errors.
import sys
import traceback

# Scheduling.
from threading import Timer

# Import models.
jobModel = ModelImporter.model('job', 'jobs')
userModel = ModelImporter.model('user')

#########
# Setup #
#########

# Set up the S3 API.
s3 = boto3.resource('s3')
bucket = s3.Bucket(BucketName)

# Set up Girder API.
gc = girder_client.GirderClient(port=8080)

# Keep track of the singleton job.
job = None

# Define the S3 Bucket Watch user.
try:
    user = userModel.createUser(PLUGIN.user, PLUGIN.password, 'S3', 'Bucket Watch', 's3_bucket_watch@s3_bucket_watch.com', admin=True)
except:
    user = userModel.findOne({'login': 's3bucketwatch'})

###########
# Helpers #
###########

# Callback after files are downloaded.
def _downloadComplete(filename, fullPath):
    _log('"' + filename + '" downloaded from bucket')
    try:
        gc.authenticate('s3bucketwatch', 's3bucketwatch')
    except:
        # Server might not be ready yet.
        return

    # Upload it to Girder
    #filename = str(uuid.uuid4()) + '-' + filename
    item = gc.createItem(gcFolderId, filename, 'from s3')
    gc.addMetadataToItem(item['_id'], {'file_source': 's3'})
    gc.uploadFileToItem(item['_id'], fullPath)

    # Delete the file in the S3 bucket.
    _log('Deleting file "' + filename + '" from bucket')
    delete = bucket.delete_objects(
    Delete={
        'Objects': [
        {
            'Key': filename
        },
        ],
        'Quiet': False
    }
    )

    # Delete the file in the local filesystem.
    os.remove(fullPath)

# Handle file download progress.
def _downloadProgress(filename):
    _log('Downloading ' + filename)
    fullPath = fileBasePath + filename
    def progress(bytesRemaining):
        _log('Bytes remaining for "' + filename + '": ' + str(bytesRemaining))
        if not bytesRemaining and os.path.exists(fullPath):
            _downloadComplete(filename, fullPath)
    return progress

# File touch utility.
def _touch(fname, times=None):
    with open(fname, 'a') as file:
        os.utime(fname, times)

# Log utility.
def _log(message):
    jobModel.updateJob(job, log=message)

########
# Main #
########

# Check for new data.
def checkForNewData():

    # Continously check for new data every X seconds.
    Timer(PLUGIN['checkeveryxseconds'], checkForNewData, ()).start()

    try:
        # For debugging: Upload test file so there's always something in the bucket.
        #bucket.upload_file('/tmp/post.json', 'post.json')

        # Look for and download any files that may exist in the bucket.
        files = bucket.objects.all()
        for file in files:
            filename = file.key
            _log('New S3 file detected: [' + BucketName + ']/' + filename)
            fullPath = fileBasePath + filename
            _touch(fullPath)
            download = bucket.download_file(filename, fullPath, None, _downloadProgress(filename))

        # All is well.
        jobModel.updateJob(job, status=JobStatus.RUNNING)

    except Exception:
        # Something went wrong while downloading/saving files.
        t, val, tb = sys.exc_info()
        message = '%s: %s\n%s' % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(job, status=JobStatus.ERROR, log=message)
        raise

def load(info):
    global job

    # Find the singleton job.
    job = jobModel.findOne({
        'userId': user['_id'],
        'title': PLUGIN['name'], 
        'type': PLUGIN['type'],
        'status': JobStatus.RUNNING,
    })

    # If the job doesn't exist, create it.
    if not job:
        job = jobModel.createJob(
            user=user,
            async=True,
            title=PLUGIN['name'], 
            type=PLUGIN['type'],
            kwargs={'buckets': ['datasift-girder-test']}
        )
        print PLUGIN['name'] + ': Created new "' + job['title'] + '" job'

    # Cancel any orphaned jobs.
    jobs = jobModel.list(user=user)
    for j in jobs:
        if j['_id'] is not job['_id']:
            jobModel.cancelJob(j)

    # Begin checking for new data.
    checkForNewData()
