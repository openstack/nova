(function() {

  var pageCache;

  $(document).ready(function() {
    pageCache = $('.api-documentation').html();

    // Show the proper JSON/XML example when toggled
    $('.example-select').on('change', function(e) {
      $(e.currentTarget).find(':selected').tab('show')
    });

    // Change the text on the expando buttons when appropriate
    $('.api-detail')
      .on('hide.bs.collapse', function(e) {
        processButton(this, 'detail');
      })
      .on('show.bs.collapse', function(e) {
        processButton(this, 'close');
      });

    var expandAllActive = true;
     // Expand the world
    $('#expand-all').click(function () {
        if (expandAllActive) {
            expandAllActive = false;
            $('.api-detail').collapse('show');
            $('#expand-all').attr('data-toggle', '');
            $(this).text('Hide All');
        } else {
            expandAllActive = true;
            $('.api-detail').collapse('hide');
            $('#expand-all').attr('data-toggle', 'collapse');
            $(this).text('Show All');
        }});

    // if ?expand_all is in the query string, then expand all
    // sections. This is useful for linking to nested elements, which
    // only work if that element is expanded.
    if (window.location.search.substring(1).indexOf("expand_all") > -1); {
      $('#expand-all').click();
    }

    // Wire up the search button
    $('#search-btn').on('click', function(e) {
      searchPage();
    });

    // Wire up the search box enter
    $('#search-box').on('keydown', function(e) {
      if (e.keyCode === 13) {
        searchPage();
        return false;
      }
    });
  });

  /**
   * highlight terms based on the regex in the provided $element
   */
  function highlightTextNodes($element, regex) {
    var markup = $element.html();

    // Do regex replace
    // Inject span with class of 'highlighted termX' for google style highlighting
    $element.html(markup.replace(regex, '>$1<span class="highlight">$2</span>$3<'));
  }

  function searchPage() {
    $(".api-documentation").html(pageCache);

    //make sure that all div's are expanded/hidden accordingly
    $('.api-detail.in').each(function (e) {
      $(this).collapse('hide');
    });

    var startTime = new Date().getTime(),
      searchTerm = $('#search-box').val();

    // The regex is the secret, it prevents text within tag declarations to be affected
    var regex = new RegExp(">([^<]*)?(" + searchTerm + ")([^>]*)?<", "ig");
    highlightTextNodes($('.api-documentation'), regex);

    // Once we've highlighted the node, lets expand any with a search match in them
    $('.api-detail').each(function () {

      var $elem = $(this);

      if ($elem.html().indexOf('<span class="highlight">') !== -1) {
        $elem.collapse('show');
        processButton($elem, 'close');
      }
    });

    // log the results
    if (console.log) {
      console.log("search completed in: " + ((new Date().getTime()) - startTime) + "ms");
    }

    $('.api-detail')
      .on('hide.bs.collapse', function (e) {
        processButton(this, 'detail');
      })
      .on('show.bs.collapse', function (e) {
        processButton(this, 'close');
      });
  }

  /**
   * Helper function for setting the text, styles for expandos
   */
  function processButton(button, text) {
    $('#' + $(button).attr('id') + '-btn').text(text)
      .toggleClass('btn-info')
      .toggleClass('btn-default');
  }
})();
