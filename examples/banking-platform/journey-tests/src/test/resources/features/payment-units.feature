@payments @ledger @reconciliation @reporting
Feature: Preserve payment value across the banking journey
  Scenario: BA verifies downstream amount conservation
    Given a synthetic USD payment of 125.50
    When payments publishes the event and all downstreams consume it
    Then the ledger posting is 125.50 USD
    And reconciliation and reporting each total 125.50 USD
  Scenario: Retry does not create a duplicate balance
    Given an accepted payment with a stable payment identifier
    When the identical payment is delivered twice
    Then reporting counts the payment once
