import logging
import boto3
import os

from api.shield.scanners.BaseScanner import Scanner

logger = logging.getLogger(__name__)


class BedrockGuardrailScanner(Scanner):
    """
    Scanner implementation for applying guard rail policies in the input prompt.
    """

    def __init__(self, **kwargs):
        """
        Initialize the GuardrailScanner with the specified parameters.

        Parameters:
            **kwargs: keyword arguments passed from properties file.
            E.g.
            name (str): The name of the scanner.
            request_types (list): List of request types that the scanner will handle.
            enforce_access_control (bool): Flag to enforce access control.
            model_path (str): Path to the model used by the scanner.
            model_score_threshold (float): Threshold score for the model to consider a match.
            entity_type (str): Type of entity the scanner is looking for.
            enable (bool): Flag to enable or disable the scanner.
        """
        super().__init__(**kwargs)

        self.guardrail_id, self.guardrail_version, self.region = self.get_guardrail_details()

        self.bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=self.region
        )

    def scan(self, message: str) -> dict:
        """
        Scan the input prompt through the Bedrock guardrail.

        Parameters:
            message (str): The input prompt that needs to be scanned.

        Returns:
            dict: Scan result including traits, actions, and output text if intervention occurs.
        """

        response = self.bedrock_client.apply_guardrail(
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.guardrail_version,
            source='OUTPUT',
            content=[{'text': {'text': message}}]
        )

        if response.get('action') == 'GUARDRAIL_INTERVENED':
            outputs = response.get('outputs', [])
            output_text = outputs[0].get('text') if outputs else None

            tag_set, action_set = set(), set()
            for assessment in response.get('assessments', []):
                # Combine assessments processing for various policies
                self.__extract_and_populate_assessment_info(assessment, tag_set, action_set)

            logger.debug(
                f"GuardrailService: Action required. Tags: {tag_set}, Actions: {action_set}, Output: {output_text}")
            return {"traits": list(tag_set), "actions": list(action_set), "output_text": output_text}

        logger.debug("GuardrailService: No action required.")
        return {}

    def get_guardrail_details(self) -> (str, str, str):
        """
        Fetch guardrail details
        """
        default_guardrail_id = self.get_property('guardrail_id')
        default_guardrail_version = self.get_property('guardrail_version')
        default_region = self.get_property('region')
        guardrail_id = os.environ.get('BEDROCK_GUARDRAIL_ID', default_guardrail_id)
        guardrail_version = os.environ.get('BEDROCK_GUARDRAIL_VERSION', default_guardrail_version)
        region = os.environ.get('BEDROCK_REGION', default_region)

        if not guardrail_id:
            logger.error("Bedrock Guardrail ID not found in properties or environment variables.")
            raise ValueError("Bedrock Guardrail ID not found in properties or environment variables.")
        if not guardrail_version:
            logger.error("Bedrock Guardrail version not found in properties or environment variables.")
            raise ValueError("Bedrock Guardrail version not found in properties or environment variables.")
        if not region:
            logger.error("Bedrock Guardrail region not found in properties or environment variables.")
            raise ValueError("Bedrock Guardrail region not found in properties or environment variables.")

        return guardrail_id, guardrail_version, region

    # noinspection PyMethodMayBeStatic
    def __extract_and_populate_assessment_info(self, assessment, tag_set: set, action_set: set) -> None:
        """
            Extract relevant information from the assessment data.
            """
        for policy in ['sensitiveInformationPolicy', 'topicPolicy', 'contentPolicy', 'wordPolicy']:
            info = assessment.get(policy, {})
            for key in ['piiEntities', 'regexes', 'topics', 'filters', 'managedWordLists', 'customWords']:
                entities = info.get(key, [])
                self.__extract_info(entities, tag_set, action_set)

    # noinspection PyMethodMayBeStatic
    def __extract_info(self, entities: list, tag_set: set, action_set: set) -> None:
        """
        Extract tag and action info from entities.
        """
        for entity in entities:
            tag_set.add((entity.get('type') or entity.get('name') or entity.get('match', '')).upper())
            action_set.add(entity.get('action'))
