import logging

from app.globals import get_answers, get_metadata, get_questionnaire_store
from app.questionnaire.navigator import Navigator, evaluate_rule
from app.templating.schema_context import build_schema_context
from app.templating.template_renderer import TemplateRenderer

from flask import g

from flask_login import current_user

logger = logging.getLogger(__name__)


def get_questionnaire_manager(schema, schema_json):
    questionnaire_manager = g.get('_questionnaire_manager')
    if questionnaire_manager is None:
        questionnaire_manager = g._questionnaire_manager = QuestionnaireManager(schema, schema_json)

    return questionnaire_manager


class QuestionnaireManager(object):

    '''
    This class represents a user journey through a survey. It models the request/response process of the web application
    '''
    def __init__(self, schema, json=None):
        self._json = json
        self._schema = schema
        self.state = None

        self.navigator = Navigator(self._json)
        self.renderer = TemplateRenderer()

    def validate(self, location, post_data):

        answers = get_answers(current_user)

        if location in self.navigator.get_location_path(answers):

            self.build_state(location, post_data)

            if self.state:
                # Todo, this doesn't feel right, validation is casting the user values to their type.
                return self.state.schema_item.validate(self.state)
            else:
                # Item has node, but is not in schema: must be introduction, thank you or summary
                return True
        else:
            # Not a validation location, so can't be valid
            return False

    def validate_all_answers(self):

        answers = get_answers(current_user)

        for location in self.navigator.get_location_path(answers):
            is_valid = self.validate(location, get_answers(current_user))

            if not is_valid:
                logger.debug("Failed validation with current location %s", location)
                return False, location

        return True, None

    def process_incoming_answers(self, location, post_data):
        logger.debug("Processing post data for %s", location)

        is_valid = self.validate(location, post_data)
        # run the validator to update the validation_store
        if is_valid:

            # Store answers in QuestionnaireStore
            questionnaire_store = get_questionnaire_store(current_user.user_id, current_user.user_ik)

            for answer in self.get_state_answers(location):
                questionnaire_store.answers[answer.id] = answer.value

            if location not in questionnaire_store.completed_blocks:
                questionnaire_store.completed_blocks.append(location)

            questionnaire_store.save()

        return is_valid

    def build_state(self, item_id, answers):
        # Build the state from the answers
        self.state = None
        if self._schema.item_exists(item_id):
            schema_item = self._schema.get_item_by_id(item_id)
            self.state = schema_item.construct_state()
            self.state.update_state(answers)
            self._conditional_display(self.state)
        if self.state:
            context = build_schema_context(get_metadata(current_user), self._schema.aliases, answers)
            self.renderer.render_state(self.state, context)

    def get_state_answers(self, item_id):
        # get the answers from the state
        if self._schema.item_exists(item_id):
            return self.state.get_answers()

        return []

    def _conditional_display(self, item):
        # Process any conditional display rules

        if item.schema_item:

            item.skipped = False

            if hasattr(item.schema_item, 'skip_condition') and item.schema_item.skip_condition:
                rule = item.schema_item.skip_condition.as_dict()
                answer = get_answers(current_user).get(rule['when']['id'])

                item.skipped = evaluate_rule(rule, answer)

            for child in item.children:
                self._conditional_display(child)

    def get_schema_item_by_id(self, item_id):
        return self._schema.get_item_by_id(item_id)

    def get_schema(self):
        return self._schema
