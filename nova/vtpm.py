#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import typing as ty

if ty.TYPE_CHECKING:
    from nova import objects

from nova import context as nova_context
from nova import crypto
from nova.virt import hardware


def get_instance_tpm_secret_security(flavor):
    secret_security = hardware.get_tpm_secret_security_constraint(flavor)
    return secret_security or 'user'


def get_or_create_secret(
    context: nova_context.RequestContext,
    instance: 'objects.Instance',
) -> tuple[str, bytes]:
    """Get or create a secret in the key manager service.

    The secret UUID and passphrase will be returned.
    """
    use_context = get_request_context(context, instance.flavor)
    return crypto.ensure_vtpm_secret(use_context, instance)


def delete_secret(
    context: nova_context.RequestContext,
    instance: 'objects.Instance',
    flavor: ty.Optional['objects.Flavor'] = None,
) -> None:
    """Delete a secret from the key manager service for TPM.

    A flavor can be optionally specified to use instead of instance.flavor.
    This will be the case for:

    * Reverting a no TPM => TPM resize because by the time we get here,
      instance.flavor will have already been changed back to the old
      flavor.

    * Confirming a TPM => no TPM resize because by the time we get here,
      instance.flavor will be set to the new flavor.
    """
    flavor = flavor or instance.flavor
    use_context = get_request_context(context, flavor)
    crypto.delete_vtpm_secret(use_context, instance)


def get_request_context(
    context: nova_context.RequestContext,
    flavor: 'objects.Flavor',
) -> nova_context.RequestContext:
    """Obtain an appropriate RequestContext based on TPM secret security.

    The normal user context should be passed in and if TPM secret security
    policy for the instance is 'deployment', this will return a Nova service
    user context. Otherwise, the normal user context that was passed in will be
    returned.
    """
    if get_instance_tpm_secret_security(flavor) == 'deployment':
        return nova_context.get_nova_service_user_context()
    return context
