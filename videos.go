package distrogo

import (
	"strconv"
	"strings"
	"time"

	"github.com/gocolly/colly"
)

const (
	VIDEO_TYPE_VIZY = iota
	VIDEO_TYPE_MINIVIDEO = iota
	VIDEO_TYPE_DISTROVID = iota
)

type Video struct {
	ID                 string
	Type               int
	Stores             []string
	Artist             string
	Uploader           string
	Title              string
	Description        string
	UploadDate         time.Time
	ReleaseDate        time.Time
	UploadDateString   string
	ReleaseDateString  string
	DistroKidViews     int
	Thumbnail          string
	AnimatedThumbnail  string
	SourceURL          string
}

func GetVideo(id string) (Video, error) {
	url := "https://distrokid.com/videos/watch/" + id
	collector := colly.NewCollector()

	var video Video
	var err error

	video.ID = id
	if strings.HasPrefix(id, "mv-") {
		video.Type = VIDEO_TYPE_MINIVIDEO
	} else if strings.HasPrefix(id, "dv-") {
		video.Type = VIDEO_TYPE_DISTROVID
	} else {
		video.Type = VIDEO_TYPE_VIZY
	}

	collector.OnError(func(r *colly.Response, e error) {
		err = e
	})

	collector.OnHTML("div.videoMetadataContainer", func(el *colly.HTMLElement) {
		video.Title = strings.TrimSpace(el.DOM.Find("div[style*=\"line-height: 1.5\"]").Nodes[0].FirstChild.Data)
		video.Uploader = el.ChildText("div.vUsername")

		if video.Type == VIDEO_TYPE_DISTROVID {
			video.Artist = el.ChildText("div[style*=\"font-weight: 400\"]")
		} else if video.Type == VIDEO_TYPE_MINIVIDEO {
			video.Title = strings.TrimSuffix(video.Title, " Mini Video") // Trim constant "Mini Video" text from title.
			// We will try getting the artist's name from recommended videos first.
		} else {
			// For Vizy videos, the title is in an "Artist - Title" format.
			splitTitle := strings.Split(video.Title, " - ")
			if len(splitTitle) > 1 {
				video.Artist = splitTitle[0]
				video.Title = splitTitle[1]
			}
		}
	})
	collector.OnHTML("div.relatedVideoCaption", func(el *colly.HTMLElement) {
		if video.Type == VIDEO_TYPE_MINIVIDEO && len(video.Artist) == 0 {
			// Get mini-video artist name from recommended videos.
			video.Artist = el.ChildText("div[style*=\"font-weight: 700\"]")
		}
	})
	collector.OnHTML("div.vMemberSince", func(el *colly.HTMLElement) {
		el.ForEach("div", func(i int, infoEl *colly.HTMLElement) {
			if (i == 1) {
				views, convErr := strconv.Atoi(strings.TrimSuffix(strings.TrimSpace(infoEl.Text), " views"))
				err = convErr
				video.DistroKidViews = views
			} else if (i == 3) {
				video.UploadDateString = strings.TrimPrefix(strings.TrimSpace(infoEl.Text), "since ")

				uploadDate, parseErr := time.Parse("Jan _2, 2006", video.UploadDateString)
				err = parseErr
				video.UploadDate = uploadDate
			}
        })
	})
	collector.OnHTML("div.vDescription", func(el *colly.HTMLElement) {
		video.Description = el.ChildText("pre")
	})
	collector.OnHTML("div.vDspContent", func(el *colly.HTMLElement) {
		el.ForEach("img.store-icon", func(i int, storeEl *colly.HTMLElement) {
			video.Stores = append(video.Stores, storeEl.Attr("title"))
		})
	})
	collector.OnHTML("div.dvMetadataSection", func(el *colly.HTMLElement) {
		// Trim "Release date:" without a space initially, so if there is no release date available,
		// the string doesn't have "Release date:" as a value, making time.Parse() fail.
		video.ReleaseDateString = strings.TrimPrefix(el.ChildText("div"), "Release date:")
		if len(video.ReleaseDateString) > 0 {
			video.ReleaseDateString = strings.TrimPrefix(video.ReleaseDateString, " ")

			releaseDate, parseErr := time.Parse("Jan _2, 2006", video.ReleaseDateString)
			err = parseErr
			video.ReleaseDate = releaseDate
		}
	})
	collector.OnHTML("video#my-player", func(el *colly.HTMLElement) {
		video.Thumbnail = el.Attr("poster")
		video.AnimatedThumbnail = video.Thumbnail[:strings.LastIndex(video.Thumbnail, "/")] + "/animated.gif"
	})
	collector.OnHTML("source[type=\"application/x-mpegURL\"]", func(el *colly.HTMLElement) {
		video.SourceURL = el.Attr("src")
	})

	collector.Visit(url)

	if video.Type == VIDEO_TYPE_MINIVIDEO && len(video.Artist) == 0 {
		// If we couldn't get the artist name for a mini-video from recommended videos,
		// closest thing we can get to an artist name is the uploader's DistroKid username.
		video.Artist = video.Uploader
	}

	return video, err
}

func GetVideos(ids []string) ([]Video, error) {
	var videos []Video
	for _, id := range ids {
		video, err := GetVideo(id)
		if err != nil {
			return videos, err
		}
		videos = append(videos, video)
	}
	return videos, nil
}
