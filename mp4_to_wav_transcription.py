import json

from datetime import timedelta

from google.protobuf.json_format import MessageToDict

from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator
from airflow.providers.google.cloud.hooks.speech_to_text import CloudSpeechToTextHook
from airflow.providers.google.cloud.operators.speech_to_text import CloudSpeechToTextRecognizeSpeechOperator
from airflow.providers.google.cloud.transfers.local_to_gcs import LocalFilesystemToGCSOperator
from airflow.providers.google.common.hooks.base_google import GoogleBaseHook
from airflow.providers.google.common.links.storage import FileDetailsLink
from airflow.utils.context import Context
from airflow.utils.dates import days_ago

gcs_bucket = 'example'
mp4_file_path = '{{ dag_run.conf["mp4_file_path"] }}'
wav_file_path = '{{ dag_run.conf["wav_file_path"] }}'
txt_file_path = '{{ dag_run.conf["txt_file_path"] }}'

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

class CloudLongSpeechToTextHook(CloudSpeechToTextHook):
    @GoogleBaseHook.quota_retry()
    def recognize_speech(
        self,
        config,
        audio,
        retry,
        timeout
    ):
        client = self.get_conn()
        operation = client.long_running_recognize(config=config, audio=audio, retry=retry, timeout=timeout)
        self.log.info("Waiting for operation to complete...")
        response = operation.result()
        return response

class CloudSpeechToTextLongRunningRecognizeSpeechOperator(CloudSpeechToTextRecognizeSpeechOperator):
    def execute(self, context: Context):
        hook = CloudLongSpeechToTextHook(
            gcp_conn_id=self.gcp_conn_id,
            impersonation_chain=self.impersonation_chain,
        )

        FileDetailsLink.persist(
            context=context,
            task_instance=self,
            # Slice from: "gs://{BUCKET_NAME}/{FILE_NAME}" to: "{BUCKET_NAME}/{FILE_NAME}"
            uri=self.audio["uri"][5:],
            project_id=self.project_id or hook.project_id,
        )

        response = hook.recognize_speech(
            config=self.config, audio=self.audio, retry=self.retry, timeout=self.timeout
        )
        return json.dumps(
            MessageToDict(response)
        )

def transcript_cleanup(transcript):
    results = json.loads(transcript)["results"]
    with open('/tmp/transcript.txt', 'w') as f:
        for result in results:
            for alternative in result["alternatives"]:
                if 'transcript' in alternative.keys():
                    f.write(alternative['transcript'] + '\n')

dag = DAG(
    'mp4_to_wav_transcription',
    default_args=default_args,
    description='Export WAV from MP4 and submit to Google Cloud Transcription',
    schedule_interval=None,  # Set to None to avoid automatic scheduling
    start_date=days_ago(1),
    catchup=False,
)

extract_wav_task = KubernetesPodOperator(
    task_id='extract_wav_from_mp4',
    namespace='composer-user-workloads',
    image='nodematic/ffmpeg-gcs:latest',
    env_vars={
        "BUCKET": gcs_bucket,
        "INPUT_FILE": mp4_file_path,
        "TRANSFORMATIONS": "-vn -acodec pcm_s16le -ar 48000 -ac 2",
        "OUTPUT_FILE": wav_file_path
    },
    is_delete_operator_pod=True,
    in_cluster=True,
    get_logs=True,
    dag=dag,
)

transcribe_wav_task = CloudSpeechToTextLongRunningRecognizeSpeechOperator(
    task_id='transcribe_wav',
    audio={"uri": f"gs://{gcs_bucket}/{wav_file_path}"},
    config={
        'encoding': 'LINEAR16',
        'sample_rate_hertz': 48000,
        'audio_channel_count': 2,
        'language_code': 'en-US',
        'model': 'video'
    },
    gcp_conn_id='google_cloud_default',
    dag=dag,
)

transcript_cleanup_task = PythonOperator(
    task_id='transcript_cleanup',
    python_callable=transcript_cleanup,
    op_args=[transcribe_wav_task.output],
    dag=dag,
)

upload_transcript_txt_task = LocalFilesystemToGCSOperator(
    task_id="upload_transcript_txt",
    src="/tmp/transcript.txt",
    dst=txt_file_path,
    bucket=gcs_bucket,
)

extract_wav_task >> transcribe_wav_task >> transcript_cleanup_task >> upload_transcript_txt_task