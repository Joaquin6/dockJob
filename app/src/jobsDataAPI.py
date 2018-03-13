from flask import request
from flask_restplus import Resource, fields, apidoc
from werkzeug.exceptions import BadRequest
import uuid
import json
import datetime
# from pytz import timezone
import pytz
from RepetitionInterval import RepetitionIntervalClass
from JobExecution import getJobExecutionCreationModel, getJobExecutionModel

#I need jobs to be stored in order so pagination works
from sortedcontainers import SortedDict

def getJobServerInfoModel(appObj):
  return appObj.flastRestPlusAPIObject.model('ServerInfoJobs', {
    'NextExecuteJob': fields.String(default='', description='Next job scheduled for execution TODO'),
    'TotalJobs': fields.Integer(default='0',description='Total Jobs')
  })

def uniqueJobName(name):
  return name.strip().upper()

#Class to represent a job
class jobClass():
  guid = None
  name = None
  command = None
  enabled = None
  repetitionInterval = None
  creationDate = None
  lastUpdateDate = None
  lastRunDate = None
  nextScheduledRun = None

  def __init__(self, name, command, enabled, repetitionInterval):
    if (len(name)<2):
      raise BadRequest('Job name must be more than 2 characters')
    curTime = datetime.datetime.now(pytz.timezone("UTC"))
    self.guid = str(uuid.uuid4())
    self.name = name
    self.command = command
    self.enabled = enabled
    self.repetitionInterval = repetitionInterval
    self.creationDate = curTime.isoformat()
    self.lastUpdateDate = curTime.isoformat()
    self.lastRunDate = None

    ri = None
    if (repetitionInterval != None):
      if (repetitionInterval != ''):
        try:
          ri = RepetitionIntervalClass(self.repetitionInterval)
        except:
          raise BadRequest('Invalid Repetition Interval')
        self.setNextScheduledRun()



  def setNextScheduledRun(self):
    ri = RepetitionIntervalClass(self.repetitionInterval)
    self.nextScheduledRun = ri.getNextOccuranceDatetime(datetime.datetime.now(pytz.timezone("UTC"))).isoformat()

  def uniqueName(self):
    return uniqueJobName(self.name)

class jobsDataClass():
  # map of guid to Job
  jobs = None
  # map of Job name to guid
  jobs_name_lookup = None
  appObj = None
  def __init__(self, appObj):
    self.jobs = SortedDict()
    self.jobs_name_lookup = SortedDict()
    self.appObj = appObj

  def getJobServerInfo(self):
    return{
      'TotalJobs': len(self.jobs),
      'NextExecuteJob': None
    }
    
  def getJob(self, guid):
    try:
      r = self.jobs[str(guid)]
    except KeyError:
      raise BadRequest('Invalid Job GUID')
    return r
  def getJobByName(self, name):
    return self.jobs[str(self.jobs_name_lookup[uniqueJobName(name)])]

  # return GUID or error
  def addJob(self, job):
    uniqueJobName = job.uniqueName()
    if (str(job.guid) in self.jobs):
      return {'msg': 'GUID already in use', 'guid':''}
    if (uniqueJobName in self.jobs_name_lookup):
      return {'msg': 'Job Name already in use - ' + uniqueJobName, 'guid':''}
    self.jobs[str(job.guid)] = job
    self.jobs_name_lookup[uniqueJobName] = job.guid
    return {'msg': 'OK', 'guid':job.guid}

  def deleteJob(self, jobObj):
    uniqueJobName = jobObj.uniqueName()
    self.jobs_name_lookup.pop(uniqueJobName)
    self.jobs.pop(jobObj.guid)
    # Delete any executions
    self.appObj.jobExecutor.deleteExecutionsForJob(jobObj.guid)

def resetData(appObj):
  appObj.appData['jobsData']=jobsDataClass(appObj)

def registerAPI(appObj):
  # Fields required to create a Job
  jobCreationModel = appObj.flastRestPlusAPIObject.model('JobCreation', {
    'name': fields.String(default=''),
    'command': fields.String(default=''),
    'enabled': fields.Boolean(default=False,description='Is the job currently enabled'),
    'repetitionInterval': fields.String(default='',description='How the job is scheduled to run'),
  })

  jobModel = appObj.flastRestPlusAPIObject.model('Job', {
    'name': fields.String(default=''),
    'command': fields.String(default=''),
    'enabled': fields.Boolean(default=False,description='Is the job currently enabled'),
    'repetitionInterval': fields.String(default='',description='How the job is scheduled to run'),
    'nextScheduledRun': fields.String(default='',description='Next scheudled run'),
    'guid': fields.String(default='',description='Unique identifier for this job'),
    'creationDate': fields.DateTime(dt_format=u'iso8601', description='Time job record was created'),
    'lastUpdateDate': fields.DateTime(dt_format=u'iso8601', description='Last time job record was changed (excluding runs)'),
    'lastRunDate': fields.DateTime(dt_format=u'iso8601', description='Last time job record was run'),
  })

  nsJobs = appObj.flastRestPlusAPIObject.namespace('jobs', description='Job Operations')
  @nsJobs.route('/')
  class jobList(Resource):
    '''Operations relating to jobs'''

    @nsJobs.doc('getjobs')
    @nsJobs.marshal_with(appObj.getResultModel(jobModel))
    @appObj.flastRestPlusAPIObject.response(200, 'Success')
    @nsJobs.param('offset', 'Number to start from')
    @nsJobs.param('pagesize', 'Results per page')
    @nsJobs.param('query', 'Search Filter')
    def get(self):
      '''Get Jobs'''
      def outputJob(item):
        return appObj.appData['jobsData'].jobs[item]
      def filterJob(item, whereClauseText): #if multiple separated by spaces each is passed individually and anded together
        if appObj.appData['jobsData'].jobs[item].name.upper().find(whereClauseText) != -1:
          return True
        if appObj.appData['jobsData'].jobs[item].command.upper().find(whereClauseText) != -1:
          return True
        return False
      return appObj.getPaginatedResult(
        appObj.appData['jobsData'].jobs_name_lookup,
        outputJob,
        request,
        filterJob
      )

    @nsJobs.doc('postjob')
    @nsJobs.expect(jobCreationModel, validate=True)
    @appObj.flastRestPlusAPIObject.response(400, 'Validation error')
    @appObj.flastRestPlusAPIObject.response(200, 'Success')
    @appObj.flastRestPlusAPIObject.marshal_with(jobModel, code=200, description='Job created')
    def post(self):
      '''Create Job'''
      content = request.get_json()
      jobObj = jobClass(content['name'], content['command'], content['enabled'], content['repetitionInterval'])
      res = appObj.appData['jobsData'].addJob(jobObj)
      if res['msg']!='OK':
        raise BadRequest(res['msg'])
      return appObj.appData['jobsData'].getJob(res['guid'])

  @nsJobs.route('/<string:guid>')
  @nsJobs.response(400, 'Job not found')
  @nsJobs.param('guid', 'Job identifier (or name)')
  class job(Resource):
    '''Show a single Job'''
    @nsJobs.doc('get_job')
    @nsJobs.marshal_with(jobModel)
    def get(self, guid):
      '''Fetch a given resource'''
      try:
        return appObj.appData['jobsData'].getJob(guid).__dict__
      except:
        try:
          return appObj.appData['jobsData'].getJobByName(guid).__dict__
        except:
          raise BadRequest('Invalid Job Identifier')
      return None

    @nsJobs.doc('delete_job')
    @nsJobs.response(200, 'Job deleted')
    @nsJobs.response(400, 'Job not found')
    def delete(self, guid):
      '''Delete job'''
      deletedJob = None
      try:
        deletedJob = appObj.appData['jobsData'].getJob(guid)
      except:
        try:
          deletedJob = appObj.appData['jobsData'].getJobByName(guid)
        except:
          raise BadRequest('Invalid Job Identifier')
      appObj.appData['jobsData'].deleteJob(deletedJob)
      return deletedJob.__dict__

  @nsJobs.route('/<string:guid>/execution')
  @nsJobs.response(400, 'Job not found')
  @nsJobs.param('guid', 'Job identifier (or name)')
  class jobExecutionList(Resource):
    @nsJobs.doc('postexecution')
    @nsJobs.expect(getJobExecutionCreationModel(appObj), validate=True)
    @appObj.flastRestPlusAPIObject.response(400, 'Validation error')
    @appObj.flastRestPlusAPIObject.response(200, 'Success')
    @appObj.flastRestPlusAPIObject.marshal_with(getJobExecutionModel(appObj), code=200, description='Job created')
    def post(self, guid):
      '''Create Job Execution'''
      content = request.get_json()
      return appObj.jobExecutor.submitJobForExecution(guid, content['name'], True)

    @nsJobs.doc('getjobexecutions')
    @nsJobs.marshal_with(appObj.getResultModel(getJobExecutionModel(appObj)))
    @appObj.flastRestPlusAPIObject.response(200, 'Success')
    @nsJobs.param('offset', 'Number to start from')
    @nsJobs.param('pagesize', 'Results per page')
    @nsJobs.param('query', 'Search Filter')
    def get(self, guid):
      '''Get Job Executions'''
      def outputJobExecution(item):
        return item
      def filterJobExecution(item, whereClauseText): #if multiple separated by spaces each is passed individually and anded together
        return True
      return appObj.getPaginatedResult(
        appObj.jobExecutor.getAllJobExecutions(guid),
        outputJobExecution,
        request,
        filterJobExecution
      )


